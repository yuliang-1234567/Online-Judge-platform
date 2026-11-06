# 使用可控父锁和可回滚事务替身；SQL 编译检查只证明发出的查询形状。
import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from sqlalchemy.dialects import mysql

from app.core.http import AppError
from app.repositories.problem import ProblemRepository
from app.repositories.test_case import TestCaseRepository as CaseRepository
from app.schemas.test_case import CaseUpdate
from app.services.problem_publication import (
    ProblemPublicationService,
    public_detail,
    validate_publication,
)
from app.services.test_case import TestCaseService as CaseService
from tests.unit.test_problem_service import MemoryAudits, MemoryTags, context, problem
from tests.unit.test_test_case_service import (
    CaseStore,
    CaseTransaction,
    LockedProblems,
    MemoryCases,
    case_body,
    case_row,
)


class PublicationProblems(LockedProblems):
    async def set_status(self, row, status):
        self.tx.fault("update")
        row.status = status

    async def published_by_id(self, problem_id):
        row = self.tx.problems.get(problem_id)
        if row is None or row.status != "PUBLISHED":
            return None
        return {col.name: getattr(row, col.name) for col in row.__table__.columns}

    async def page_published(self, *, page, size, difficulty, tag_id, q):
        rows = []
        for key in sorted(self.tx.problems, reverse=True):
            row = await self.published_by_id(key)
            if row is None or (difficulty and row["difficulty"] != difficulty):
                continue
            if tag_id is not None and tag_id not in self.tx.links.get(key, []):
                continue
            if q in row["title"] or q in row["slug"]:
                rows.append(row)
        return rows[(page - 1) * size : page * size], len(rows)


class PublicationCases(MemoryCases):
    async def locked_publication_rows(self, problem_id):
        assert self.tx.held_lock is not None and self.tx.held_lock.locked()
        return [
            (row.id, row.is_sample)
            for row in self.tx.cases.values()
            if row.problem_id == problem_id
        ]

    async def public_samples(self, problem_id):
        return [
            {
                "case_index": row.case_index,
                "input_data": row.input_data,
                "expected_output": row.expected_output,
            }
            for row in sorted(
                self.tx.cases.values(), key=lambda row: (row.case_index, row.id)
            )
            if row.problem_id == problem_id and row.is_sample
        ]


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.mark.parametrize(
    "count,limit,expected", [(50, 1000, 170_000), (50, 1200, 180_000)]
)
def test_publication_accepts_budget_boundary(count, limit, expected):
    row = problem()
    row.time_limit_ms = limit
    cases = [(key, key == 1) for key in range(1, count + 1)]
    assert validate_publication(row, cases) == expected


def test_publication_rejects_one_ms_over_budget():
    row = problem()
    row.time_limit_ms = 158_001
    assert row.time_limit_ms + 2_000 + 20_000 == 180_001
    with pytest.raises(AppError, match="CONFLICT") as result:
        validate_publication(row, [(1, True)])
    assert result.value.status == 409
    assert result.value.message == "题目时间预算超过发布上限，请减少测试点或降低时限"


def test_public_detail_uses_nested_whitelist():
    row = dict(
        id=1,
        slug="sum",
        title="Sum",
        description="Body",
        difficulty="EASY",
        time_limit_ms=1000,
        memory_limit_mb=256,
        created_by=9,
        status="PUBLISHED",
        secret="sentinel",
    )
    tags = [SimpleNamespace(id=2, name="数组", created_at="internal")]
    samples = [
        dict(case_index=4, input_data="1\n", expected_output="1\n", sha256="internal")
    ]
    assert public_detail(row, tags, samples).model_dump() == {
        "id": 1,
        "slug": "sum",
        "title": "Sum",
        "description": "Body",
        "difficulty": "EASY",
        "time_limit_ms": 1000,
        "memory_limit_mb": 256,
        "tags": [{"id": 2, "name": "数组"}],
        "samples": [{"case_index": 4, "input_data": "1\n", "expected_output": "1\n"}],
    }


@pytest.mark.anyio
@pytest.mark.parametrize("competitor", ["publish", "edit"])
async def test_publication_serializes_with_other_parent_lock_writes(competitor):
    store = CaseStore()
    store.cases[1] = case_row(is_sample=True)
    first_tx, second_tx = CaseTransaction(store), CaseTransaction(store)
    first_holds_lock, second_started, release = (
        asyncio.Event(),
        asyncio.Event(),
        asyncio.Event(),
    )

    class HeldCases(PublicationCases):
        async def locked_publication_rows(self, problem_id):
            result = await super().locked_publication_rows(problem_id)
            first_holds_lock.set()
            await release.wait()
            return result

    class WaitingProblems(PublicationProblems):
        async def lock_by_id(self, key):
            second_started.set()
            return await super().lock_by_id(key)

    first = ProblemPublicationService(
        first_tx,
        PublicationProblems(first_tx),
        MemoryTags(first_tx),
        HeldCases(first_tx),
        MemoryAudits(first_tx),
    )
    problems = WaitingProblems(second_tx)
    audits = MemoryAudits(second_tx)
    second_publish = ProblemPublicationService(
        second_tx,
        problems,
        MemoryTags(second_tx),
        PublicationCases(second_tx),
        audits,
    )
    second_edit = CaseService(second_tx, problems, MemoryCases(second_tx), audits)

    async def compete():
        if competitor == "publish":
            return await second_publish.transition(1, "PUBLISHED", **context())
        return await second_edit.update_case(1, CaseUpdate(**case_body()), **context())

    first_task = asyncio.create_task(first.transition(1, "PUBLISHED", **context()))
    tasks = [first_task]
    try:
        await asyncio.wait_for(first_holds_lock.wait(), timeout=2)
        second_task = asyncio.create_task(compete())
        tasks.append(second_task)
        await asyncio.wait_for(second_started.wait(), timeout=2)
        assert not second_task.done() and store.problems[1].status == "DRAFT"
        release.set()
        results = await asyncio.wait_for(
            asyncio.gather(*tasks, return_exceptions=True), timeout=2
        )
        assert results[0] == {"id": 1, "status": "PUBLISHED"}
        assert isinstance(results[1], AppError) and results[1].status == 409
        assert [row.action for row in store.audits] == ["PUBLISH_PROBLEM"]
        assert store.cases[1].is_sample
    finally:
        release.set()
        for task in tasks:
            if not task.done():
                task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)


@pytest.mark.anyio
async def test_publication_repository_projections_and_sql_filters():
    rows = Mock()
    rows.all.return_value = [(10, True)]
    rows.mappings.return_value.all.return_value = []
    rows.mappings.return_value.one_or_none.return_value = None
    session = SimpleNamespace(
        execute=AsyncMock(return_value=rows), scalar=AsyncMock(return_value=10)
    )
    problems, cases = ProblemRepository(session), CaseRepository(session)
    assert await cases.locked_publication_rows(1) == [(10, True)]
    await cases.public_samples(1)
    await problems.published_by_id(1)
    await problems.page_published(
        page=2, size=3, difficulty="EASY", tag_id=2, q="a%_/b"
    )

    locked, samples, detail, page = [
        call.args[0] for call in session.execute.await_args_list
    ]
    count = session.scalar.await_args.args[0]
    dialect = mysql.dialect()
    assert list(locked.selected_columns.keys()) == ["id", "is_sample"]
    assert "FOR UPDATE" in str(locked.compile(dialect=dialect))
    assert list(samples.selected_columns.keys()) == [
        "case_index",
        "input_data",
        "expected_output",
    ]
    sample_sql = str(samples.compile(dialect=dialect))
    assert "test_cases.is_sample IS true" in sample_sql
    assert "ORDER BY test_cases.case_index, test_cases.id" in sample_sql
    assert "PUBLISHED" in samples.compile(dialect=dialect).params.values()
    assert "description" in detail.selected_columns.keys()
    assert "PUBLISHED" in detail.compile(dialect=dialect).params.values()
    assert list(page.selected_columns.keys()) == [
        "id",
        "slug",
        "title",
        "difficulty",
        "time_limit_ms",
        "memory_limit_mb",
    ]
    count_sql, page_sql = count.compile(dialect=dialect), page.compile(dialect=dialect)
    assert (
        str(count_sql).split("WHERE ", 1)[1]
        == str(page_sql).split("WHERE ", 1)[1].split(" ORDER BY", 1)[0]
    )
    assert str(page_sql).count("ESCAPE '/'") == 2
    assert "EXISTS" in str(page_sql) and "ORDER BY problems.id DESC" in str(page_sql)
    assert list(page_sql.params.values()).count("a/%/_//b") == 2
