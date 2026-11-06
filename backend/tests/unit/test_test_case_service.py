# 可控父题目锁和事务快照验证编排；不能证明真实 InnoDB 并发、回滚或外键效果。
import asyncio
import hashlib
from contextlib import asynccontextmanager
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from pydantic import ValidationError
from sqlalchemy.dialects import mysql
from sqlalchemy.exc import OperationalError
from sqlalchemy.exc import TimeoutError as PoolTimeout
from sqlalchemy.schema import CreateTable

from app.core.http import AppError
from app.models.test_case import TestCase as CaseModel
from app.repositories.problem import ProblemRepository
from app.repositories.test_case import TestCaseRepository as CaseRepository
from app.schemas.problem import ProblemUpdate
from app.schemas.test_case import DATA_LIMIT, CaseCreate, CaseUpdate
from app.services.problem import ProblemService
from app.services.test_case import (
    TestCaseService as CaseService,
)
from app.services.test_case import (
    calculate_case_metadata,
    classify_case_error,
)
from tests.unit.test_problem_service import (
    NOW,
    MemoryAudits,
    MemoryProblems,
    MemoryTags,
    Store,
    Transaction,
    body,
    context,
    db_error,
    problem,
)

TABLES = ("problems", "tags", "links", "audits", "users", "cases", "history")


def case_body(**changes):
    return {
        "case_index": 1,
        "is_sample": False,
        "input_data": "private-input\n",
        "expected_output": "private-output\n",
        **changes,
    }


def case_row(key=1, **changes):
    values = case_body(**changes)
    return CaseModel(
        id=key,
        problem_id=1,
        **values,
        **calculate_case_metadata(values["input_data"], values["expected_output"]),
        created_at=NOW,
        updated_at=NOW,
    )


class CaseStore(Store):
    def __init__(self):
        super().__init__()
        self.problems[1] = problem()
        self.cases = {}
        self.history = {1: {"case_index": 99, "is_sample": True}}
        self.inflight = {}
        self.locks = {}


class CaseTransaction(Transaction):
    @asynccontextmanager
    async def begin(self):
        self.changed, self.held_lock = False, None
        self.fault("begin")
        self.snapshot()
        try:
            yield
            self.fault("commit")
            for name in TABLES:
                setattr(self.store, name, getattr(self, name))
        except BaseException:
            self.store.events.append("rollback")
            raise
        finally:
            if self.held_lock is not None:
                self.held_lock.release()

    def snapshot(self):
        for name in TABLES:
            setattr(self, name, deepcopy(getattr(self.store, name)))


class LockedProblems(MemoryProblems):
    async def lock_by_id(self, key):
        self.tx.fault("lock")
        lock = self.tx.store.locks.setdefault(key, asyncio.Lock())
        await lock.acquire()
        self.tx.held_lock = lock
        # 等待父锁后重取当前值，不能沿用等待之前的事务替身快照。
        self.tx.snapshot()
        return self.tx.problems.get(key)


class MemoryCases:
    def __init__(self, tx):
        self.tx = tx

    async def problem_id_for(self, key):
        self.tx.fault("locate")
        row = self.tx.cases.get(key)
        return row.problem_id if row else None

    async def lock_by_id(self, key, problem_id):
        self.tx.fault("case_lock")
        row = self.tx.cases.get(key)
        return row if row and row.problem_id == problem_id else None

    async def locked_ids(self, problem_id):
        self.tx.fault("count")
        return [
            row.id for row in self.tx.cases.values() if row.problem_id == problem_id
        ]

    def unique(self, problem_id, case_index, excluded=None):
        if any(
            row.problem_id == problem_id
            and row.case_index == case_index
            and row.id != excluded
            for row in self.tx.cases.values()
        ):
            raise db_error(1062, "private value for key 'uk_cases_problem_idx'")

    async def create(self, *, problem_id, **values):
        self.tx.fault("create")
        self.unique(problem_id, values["case_index"])
        await asyncio.sleep(0)
        row = CaseModel(
            id=max(self.tx.cases, default=0) + 1,
            problem_id=problem_id,
            **values,
            created_at=NOW,
            updated_at=NOW,
        )
        self.tx.cases[row.id] = row
        return row

    async def update(self, row, **values):
        self.tx.fault("update")
        self.unique(row.problem_id, values["case_index"], row.id)
        for name, value in values.items():
            setattr(row, name, value)
        row.updated_at = NOW

    async def delete(self, row):
        self.tx.fault("delete")
        self.tx.changed = True
        del self.tx.cases[row.id]

    async def page(self, problem_id, *, page, size):
        self.tx.fault("read")
        rows = sorted(
            (row for row in self.tx.cases.values() if row.problem_id == problem_id),
            key=lambda row: (row.case_index, row.id),
        )
        return rows[(page - 1) * size : page * size], len(rows)


def case_service(store):
    tx = CaseTransaction(store)
    return CaseService(tx, LockedProblems(tx), MemoryCases(tx), MemoryAudits(tx))


@pytest.fixture
def anyio_backend():
    return "asyncio"


def test_metadata_fixed_utf8_vector_and_framing(monkeypatch):
    original, payloads = hashlib.sha256, []

    def capture(data):
        payloads.append(data)
        return original(data)

    monkeypatch.setattr("app.services.test_case.hashlib.sha256", capture)
    result = calculate_case_metadata("中\n", "OK\n")
    assert result == {
        "input_size": 4,
        "output_size": 3,
        "sha256": "f3fc3a9bea58ac50c6d1ab7fdb7b81c0cce0dffcb05504a1f027fb5ef75e4209",
    }
    assert payloads[0].hex() == "0000000000000004e4b8ad0a00000000000000034f4b0a"
    assert (
        calculate_case_metadata("a", "bc")["sha256"]
        != calculate_case_metadata("ab", "c")["sha256"]
    )


@pytest.mark.parametrize("field", ["input_data", "expected_output"])
def test_utf8_byte_limit_is_per_field_and_preserves_content(field):
    exact = "中" * (DATA_LIMIT // 3) + "a"
    assert len(exact.encode()) == DATA_LIMIT
    assert CaseCreate(**case_body(**{field: exact})).model_dump()[field] == exact
    with pytest.raises(ValidationError):
        CaseCreate(**case_body(**{field: exact + "a"}))
    assert CaseCreate(**case_body(input_data="", expected_output="")).input_data == ""


@pytest.mark.parametrize("field", ["input_data", "expected_output"])
def test_unencodable_surrogate_is_validation_error(field):
    with pytest.raises(ValidationError):
        CaseCreate(**case_body(**{field: "\ud800"}))


@pytest.mark.parametrize(
    "error, status",
    [
        (db_error(1062, "private for key 'uk_cases_problem_idx'"), 409),
        (db_error(1062, "private for key 'test_cases.uk_cases_problem_idx'"), 409),
        (db_error(1062, "private for key 'uk_cases_problem_idx_extra'"), 500),
        (db_error(1062, "private uk_cases_problem_idx"), 500),
        (db_error(1062, "private for key 'PRIMARY'"), 500),
        (db_error(1062, "private for key 'uk_cases_problem_idx' trailing"), 500),
        (db_error(1452, "private for key 'uk_cases_problem_idx'"), 500),
        (db_error(999, "private for key 'uk_cases_problem_idx'"), 500),
    ],
)
def test_case_constraint_mapping_requires_code_and_exact_key(error, status):
    result = classify_case_error(error)
    assert result.status == status and "private" not in result.message


@pytest.mark.anyio
@pytest.mark.parametrize("state", ["DRAFT", "OFFLINE"])
async def test_case_write_lifecycle_audit_and_parent_lock(state):
    store = CaseStore()
    store.problems[1].status = state
    created = await case_service(store).create_case(
        1, CaseCreate(**case_body()), **context()
    )
    assert store.events[:4] == ["begin", "lock", "inflight", "count"]
    assert created.input_size == len(created.input_data.encode())
    assert store.audits[-1].action == "CREATE_TEST_CASE"
    updated = await case_service(store).update_case(
        created.id,
        CaseUpdate(**case_body(case_index=8, is_sample=True, input_data="")),
        **context(),
    )
    assert updated.input_size == 0 and updated.case_index == 8 and updated.is_sample
    start = store.events.index("locate")
    assert store.events[start : start + 4] == [
        "locate",
        "lock",
        "case_lock",
        "inflight",
    ]
    assert store.audits[-1].action == "UPDATE_TEST_CASE"
    await case_service(store).delete_case(created.id, **context())
    assert store.cases == {} and store.audits[-1].action == "DELETE_TEST_CASE"
    assert store.history == {1: {"case_index": 99, "is_sample": True}}
    assert all(
        "private-input" not in row.payload_summary
        and "private-output" not in row.payload_summary
        and row.ip == "2001:db8::1"
        and len(row.payload_summary) <= 2048
        for row in store.audits
    )


async def operate(store, operation):
    if operation == "create":
        return await case_service(store).create_case(
            1, CaseCreate(**case_body(case_index=2)), **context()
        )
    if operation == "update":
        return await case_service(store).update_case(
            1, CaseUpdate(**case_body(case_index=2)), **context()
        )
    return await case_service(store).delete_case(1, **context())


@pytest.mark.anyio
@pytest.mark.parametrize("operation", ["create", "update", "delete"])
@pytest.mark.parametrize("state", ["QUEUED", "RUNNING"])
async def test_inflight_rejects_every_case_mutation_without_partial_result(
    operation, state
):
    store = CaseStore()
    store.cases[1] = case_row()
    store.inflight[1] = state
    with pytest.raises(AppError) as error:
        await operate(store, operation)
    assert error.value.status == 409
    assert store.cases[1].case_index == 1 and store.audits == []
    assert not any(
        event in store.events for event in ("create", "update", "delete", "audit")
    )
    assert store.events[-1] == "rollback"


@pytest.mark.anyio
@pytest.mark.parametrize("operation", ["create", "update", "delete"])
async def test_published_rejects_all_writes(operation):
    store = CaseStore()
    store.cases[1] = case_row()
    store.problems[1].status = "PUBLISHED"
    with pytest.raises(AppError) as error:
        await operate(store, operation)
    assert error.value.status == 409 and store.audits == []


@pytest.mark.anyio
@pytest.mark.parametrize("operation", ["create", "update", "delete"])
@pytest.mark.parametrize("stage", ["write", "audit", "commit"])
async def test_case_faults_roll_back_business_and_audit(operation, stage):
    store = CaseStore()
    store.cases[1] = case_row()
    store.failure = operation if stage == "write" else stage
    with pytest.raises(RuntimeError):
        await operate(store, operation)
    assert list(store.cases) == [1] and store.cases[1].case_index == 1
    assert store.audits == [] and store.events[-1] == "rollback"
    if stage == "commit":
        assert "audit" in store.events


@pytest.mark.anyio
@pytest.mark.parametrize("count", [49, 50])
async def test_fifty_case_limit_inside_parent_lock(count):
    store = CaseStore()
    store.cases = {i: case_row(i, case_index=i) for i in range(1, count + 1)}
    if count == 49:
        await case_service(store).create_case(
            1, CaseCreate(**case_body(case_index=50)), **context()
        )
        assert len(store.cases) == 50
    else:
        with pytest.raises(AppError) as error:
            await case_service(store).create_case(
                1, CaseCreate(**case_body(case_index=51)), **context()
            )
        assert error.value.status == 422 and len(store.cases) == 50 and not store.audits


@pytest.mark.anyio
@pytest.mark.parametrize("duplicate", [False, True])
async def test_competing_creates_use_parent_lock_and_current_count(duplicate):
    store = CaseStore()
    if not duplicate:
        store.cases = {i: case_row(i, case_index=i) for i in range(1, 50)}

    async def create(index):
        try:
            await case_service(store).create_case(
                1,
                CaseCreate(**case_body(case_index=index)),
                **context(),
            )
            return 201
        except AppError as error:
            return error.status

    results = await asyncio.wait_for(
        asyncio.gather(
            create(1 if duplicate else 50),
            create(1 if duplicate else 51),
        ),
        timeout=2,
    )
    assert sorted(results) == [201, 409 if duplicate else 422]
    assert len(store.cases) == (1 if duplicate else 50) and len(store.audits) == 1


@pytest.mark.anyio
async def test_missing_case_and_disappeared_target_are_404():
    store = CaseStore()
    with pytest.raises(AppError) as error:
        await case_service(store).delete_case(999, **context())
    assert error.value.status == 404
    store.cases[1] = case_row()
    subject = case_service(store)
    subject.cases.lock_by_id = AsyncMock(return_value=None)
    with pytest.raises(AppError) as error:
        await subject.delete_case(1, **context())
    assert error.value.status == 404 and store.cases and not store.audits


@pytest.mark.anyio
@pytest.mark.parametrize("state", ["DRAFT", "OFFLINE"])
@pytest.mark.parametrize("inflight", ["QUEUED", "RUNNING"])
@pytest.mark.parametrize("changed", [False, True])
@pytest.mark.parametrize("field", ["time_limit_ms", "memory_limit_mb"])
async def test_problem_limits_guard_uses_locked_values(state, inflight, changed, field):
    store = CaseStore()
    store.problems[1].status = state
    store.inflight[1] = inflight
    tx = CaseTransaction(store)
    subject = ProblemService(tx, LockedProblems(tx), MemoryTags(tx), MemoryAudits(tx))
    data = {
        k: v
        for k, v in body(
            **{field: 2000 if changed else (1000 if field == "time_limit_ms" else 256)}
        ).items()
        if k != "slug"
    }
    if changed:
        with pytest.raises(AppError) as error:
            await subject.update_problem(1, ProblemUpdate(**data), **context())
        assert error.value.status == 409 and store.problems[1].title == "old title"
        assert store.audits == []
    else:
        await subject.update_problem(1, ProblemUpdate(**data), **context())
        assert "inflight" not in store.events and len(store.audits) == 1


@pytest.mark.anyio
@pytest.mark.parametrize(
    "error", [OperationalError("private", {}, Exception(1213)), PoolTimeout("private")]
)
async def test_case_dependency_failure_is_safe_503(error):
    store = CaseStore()
    store.failure, store.failure_error = "lock", error
    with pytest.raises(AppError) as caught:
        await case_service(store).create_case(1, CaseCreate(**case_body()), **context())
    assert caught.value.status == 503 and "private" not in caught.value.message


@pytest.mark.anyio
async def test_repository_sql_uses_current_reads_and_no_independent_commit():
    row = case_row()
    session = SimpleNamespace(
        scalar=AsyncMock(return_value=1),
        scalars=AsyncMock(return_value=SimpleNamespace(all=lambda: [row])),
        flush=AsyncMock(),
        refresh=AsyncMock(),
        delete=AsyncMock(),
        add=lambda obj: None,
    )
    parent = ProblemRepository(session)
    assert await parent.has_inflight(7) is True
    query = session.scalar.call_args.args[0]
    sql = str(query.compile(dialect=mysql.dialect()))
    assert sql.endswith("FOR UPDATE") and "LIMIT" in sql
    assert query.compile().params["problem_id_1"] == 7
    assert query.compile().params["status_1"] == ["QUEUED", "RUNNING"]
    session.scalar.return_value = None
    assert await parent.has_inflight(7) is False
    repo = CaseRepository(session)
    await repo.problem_id_for(1)
    assert "FOR UPDATE" not in str(session.scalar.call_args.args[0])
    await repo.lock_by_id(1, 7)
    query = session.scalar.call_args.args[0]
    assert query.get_execution_options()["populate_existing"] is True
    assert str(query.compile(dialect=mysql.dialect())).endswith("FOR UPDATE")
    await repo.locked_ids(7)
    assert str(
        session.scalars.call_args.args[0].compile(dialect=mysql.dialect())
    ).endswith("FOR UPDATE")
    await repo.create(problem_id=1, **case_body(), **calculate_case_metadata("", ""))
    await repo.update(row, **case_body(), **calculate_case_metadata("", ""))
    await repo.delete(row)
    assert session.flush.await_count == 3 and session.delete.await_count == 1
    assert not hasattr(session, "commit")
    await repo.page(1, page=2, size=3)
    query = session.scalars.call_args.args[0]
    assert "ORDER BY test_cases.case_index, test_cases.id" in str(query)
    assert query.compile().params["param_1"] == 3


def test_test_case_model_matches_existing_ddl():
    table = CaseModel.__table__
    assert len(table.columns) == 11
    assert table.c.case_index.type.unsigned and table.c.problem_id.type.unsigned
    assert isinstance(table.c.input_data.type, mysql.MEDIUMTEXT)
    assert table.c.sha256.type.length == 64
    assert {c.name for c in table.constraints if c.name} == {
        "uk_cases_problem_idx",
        "fk_cases_problem",
    }
    ddl = str(CreateTable(table).compile(dialect=mysql.dialect()))
    assert "ON DELETE RESTRICT ON UPDATE RESTRICT" in ddl
    assert "utf8mb4_0900_ai_ci" in ddl
    assert "CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3)" in ddl
