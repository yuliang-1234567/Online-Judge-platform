# 可回滚事务替身截住存储边界；证明服务编排，不声称真实 MySQL 锁或持久化。
from contextlib import asynccontextmanager
from copy import deepcopy
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy.dialects import mysql
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.exc import TimeoutError as PoolTimeout
from sqlalchemy.schema import CreateTable

from app.core.http import AppError
from app.models.problem import Problem, ProblemTag, Tag
from app.models.user import User
from app.repositories.problem import ProblemRepository, TagRepository
from app.schemas.problem import ProblemCreate, ProblemUpdate, TagCreate
from app.services.problem import ProblemService, classify_write_error

NOW = datetime(2026, 11, 5, 2, 0, 0, 123000, tzinfo=UTC)


def body(**changes):
    return {
        "slug": "two-sum",
        "title": " 两数之和 ",
        "description": "private-description",
        "difficulty": "EASY",
        "tag_ids": [1],
        "time_limit_ms": 1000,
        "memory_limit_mb": 256,
        **changes,
    }


def problem(**changes):
    return Problem(
        id=1,
        slug="old-slug",
        title="old title",
        description="old body",
        difficulty="EASY",
        time_limit_ms=1000,
        memory_limit_mb=256,
        status="DRAFT",
        created_by=1,
        created_at=NOW,
        updated_at=NOW,
        **changes,
    )


def db_error(code, message):
    return IntegrityError(
        "PRIVATE SQL", {"private": "private-parameter"}, Exception(code, message)
    )


class Store:
    def __init__(self):
        self.problems = {}
        self.tags = {1: Tag(id=1, name="数组", created_at=NOW)}
        self.links = {}
        self.audits = []
        self.users = {
            key: User(
                id=key,
                username=f"user_{key}",
                password_hash="offline-hash",
                role=role,
                status=status,
                created_at=NOW,
            )
            for key, role, status in (
                (1, "ADMIN", "ACTIVE"),
                (2, "USER", "ACTIVE"),
                (3, "ADMIN", "DISABLED"),
            )
        }
        self.failure = None
        self.failure_error = RuntimeError("private-storage-failure")
        self.events = []


class Transaction:
    def __init__(self, store):
        self.store = store

    def fault(self, stage):
        self.store.events.append(stage)
        if stage in {"create", "update", "links", "audit"}:
            self.changed = True
        if self.store.failure == stage and (stage != "commit" or self.changed):
            raise self.store.failure_error

    @asynccontextmanager
    async def begin(self):
        # 鉴权的只读事务不触发业务 commit 故障，确保 API 测试真的走过写入/审计。
        self.changed = False
        self.fault("begin")
        for name in ("problems", "tags", "links", "audits", "users"):
            setattr(self, name, deepcopy(getattr(self.store, name)))
        try:
            yield
            self.fault("commit")
            for name in ("problems", "tags", "links", "audits", "users"):
                setattr(self.store, name, getattr(self, name))
        except BaseException:
            self.store.events.append("rollback")
            raise


class MemoryProblems:
    def __init__(self, tx):
        self.tx = tx

    async def create(self, *, created_by, **values):
        self.tx.fault("create")
        obj = Problem(
            id=max(self.tx.problems, default=0) + 1,
            **values,
            status="DRAFT",
            created_by=created_by,
            created_at=NOW,
            updated_at=NOW,
        )
        self.tx.problems[obj.id] = obj
        return obj

    async def by_id(self, key):
        self.tx.fault("read")
        return self.tx.problems.get(key)

    async def lock_by_id(self, key):
        self.tx.fault("lock")
        return self.tx.problems.get(key)

    async def has_inflight(self, key):
        self.tx.fault("inflight")
        return bool(getattr(self.tx.store, "inflight", {}).get(key))

    async def update(self, obj, **values):
        self.tx.fault("update")
        for key, value in values.items():
            setattr(obj, key, value)

    async def replace_tags(self, key, ids):
        self.tx.fault("links")
        self.tx.links[key] = list(ids)

    async def page(self, *, page, size):
        self.tx.fault("read")
        objects = sorted(self.tx.problems.values(), key=lambda p: p.id, reverse=True)
        return [
            {
                column.name: getattr(p, column.name)
                for column in Problem.__table__.columns
                if column.name != "description"
            }
            for p in objects[(page - 1) * size : page * size]
        ], len(objects)


class MemoryTags:
    def __init__(self, tx):
        self.tx = tx

    async def by_ids(self, ids):
        self.tx.fault("tags")
        return [self.tx.tags[key] for key in sorted(ids) if key in self.tx.tags]

    async def for_problems(self, ids):
        return {
            key: [self.tx.tags[t] for t in sorted(self.tx.links.get(key, []))]
            for key in ids
        }

    async def create(self, name):
        self.tx.fault("create")
        obj = Tag(id=max(self.tx.tags, default=0) + 1, name=name, created_at=NOW)
        self.tx.tags[obj.id] = obj
        return obj

    async def page(self, *, page, size):
        self.tx.fault("read")
        rows = sorted(self.tx.tags.values(), key=lambda t: t.id, reverse=True)
        return rows[(page - 1) * size : page * size], len(rows)


class MemoryAudits:
    def __init__(self, tx):
        self.tx = tx

    async def append(self, **values):
        self.tx.fault("audit")
        self.tx.audits.append(
            SimpleNamespace(id=len(self.tx.audits) + 1, created_at=NOW, **values)
        )


def service(store):
    tx = Transaction(store)
    return ProblemService(tx, MemoryProblems(tx), MemoryTags(tx), MemoryAudits(tx))


def context():
    return {"actor_id": 1, "request_id": "offline-request", "ip": "2001:0db8::1"}


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.mark.anyio
async def test_create_commits_problem_links_and_safe_audit_together():
    store = Store()
    result = await service(store).create_problem(ProblemCreate(**body()), **context())
    assert (result.id, result.slug, result.status, result.created_by) == (
        1,
        "two-sum",
        "DRAFT",
        1,
    )
    assert store.links == {1: [1]}
    assert [tag.id for tag in result.tags] == [1]
    audit = store.audits[0]
    assert (audit.action, audit.resource_type, audit.resource_id) == (
        "CREATE_PROBLEM",
        "PROBLEM",
        1,
    )
    assert (audit.request_id, audit.ip) == ("offline-request", "2001:db8::1")
    assert "private-description" not in audit.payload_summary
    assert "两数之和" not in audit.payload_summary
    assert store.events == ["begin", "tags", "create", "links", "audit", "commit"]


@pytest.mark.anyio
async def test_unknown_tag_rejects_before_problem_insert():
    store = Store()
    with pytest.raises(AppError) as error:
        await service(store).create_problem(
            ProblemCreate(**body(tag_ids=[999])), **context()
        )
    assert error.value.status == 422 and error.value.message == "标签不存在"
    assert store.problems == {} and store.links == {} and store.audits == []
    assert store.events == ["begin", "tags", "rollback"]


@pytest.mark.anyio
@pytest.mark.parametrize("operation", ["create", "update"])
@pytest.mark.parametrize("stage", ["create", "links", "audit", "commit"])
async def test_write_failure_has_no_partial_problem_links_or_audit(operation, stage):
    if operation == "update" and stage == "create":
        stage = "update"
    store = Store()
    store.problems[1] = problem()
    store.links[1] = [1]
    store.failure = stage
    with pytest.raises(RuntimeError, match="private-storage-failure"):
        if operation == "create":
            await service(store).create_problem(ProblemCreate(**body()), **context())
        else:
            data = {k: v for k, v in body(tag_ids=[]).items() if k != "slug"}
            await service(store).update_problem(1, ProblemUpdate(**data), **context())
    assert len(store.problems) == 1
    assert (store.problems[1].title, store.problems[1].slug) == (
        "old title",
        "old-slug",
    )
    assert store.links == {1: [1]} and store.audits == []
    assert store.events[-1] == "rollback"


@pytest.mark.anyio
@pytest.mark.parametrize("stage", ["audit", "commit"])
async def test_tag_creation_and_audit_roll_back_together(stage):
    store = Store()
    store.failure = stage
    with pytest.raises(RuntimeError):
        await service(store).create_tag(TagCreate(name=" 新标签 "), **context())
    assert list(store.tags) == [1] and store.audits == []


@pytest.mark.anyio
async def test_update_locks_draft_and_replaces_limits_and_clears_tags():
    store = Store()
    store.problems[1] = problem()
    store.links[1] = [1]
    values = {
        k: v
        for k, v in body(
            tag_ids=[], time_limit_ms=1, memory_limit_mb=4294967295
        ).items()
        if k != "slug"
    }
    result = await service(store).update_problem(
        1, ProblemUpdate(**values), **context()
    )
    assert result.slug == "old-slug" and result.created_by == 1
    assert (result.time_limit_ms, result.memory_limit_mb) == (1, 4294967295)
    assert result.tags == [] and store.links == {1: []}
    assert store.events[:4] == ["begin", "lock", "inflight", "tags"]
    assert store.audits[0].action == "UPDATE_PROBLEM"


@pytest.mark.anyio
@pytest.mark.parametrize("status", ["PUBLISHED"])
async def test_non_draft_is_409_without_changes(status):
    store = Store()
    obj = problem()
    obj.status = status
    store.problems[1] = obj
    with pytest.raises(AppError) as error:
        await service(store).update_problem(
            1,
            ProblemUpdate(**{k: v for k, v in body().items() if k != "slug"}),
            **context(),
        )
    assert error.value.status == 409
    assert store.problems[1].status == status and store.audits == []


@pytest.mark.anyio
async def test_missing_problem_is_404_without_audit():
    store = Store()
    with pytest.raises(AppError) as error:
        await service(store).update_problem(
            99,
            ProblemUpdate(**{k: v for k, v in body().items() if k != "slug"}),
            **context(),
        )
    assert error.value.status == 404 and store.audits == []


@pytest.mark.parametrize(
    ("code", "message", "expected"),
    [
        (1062, "private value for key 'uk_problems_slug'", 409),
        (1062, "private value for key 'problems.uk_problems_slug'", 409),
        (1062, "private value for key 'uk_tags_name'", 409),
        (1062, "private value for key 'tags.uk_tags_name'", 409),
        (1062, "private value for key 'PRIMARY'", 500),
        (1062, "private value for key 'uk_users_username'", 500),
        (1062, "private uk_problems_slug without key field", 500),
        (1062, "private value for key 'uk_problems_slug_extra'", 500),
        (1062, "private value for key 'uk_problems_slug' trailing", 500),
        (
            1452,
            "private CONSTRAINT "
            + chr(96)
            + "fk_problem_tags_tag"
            + chr(96)
            + " FOREIGN KEY (tag_id)",
            422,
        ),
        (
            1452,
            "private CONSTRAINT 'fk_problems_creator' FOREIGN KEY (created_by)",
            500,
        ),
        (1452, "private fk_problem_tags_tag without constraint field", 500),
        (
            1452,
            "private CONSTRAINT 'fk_problem_tags_tag_extra' FOREIGN KEY (tag_id)",
            500,
        ),
        (999, "private value for key 'uk_problems_slug'", 500),
    ],
)
def test_constraint_code_and_exact_name_are_both_required(code, message, expected):
    error = classify_write_error(db_error(code, message))
    assert error.status == expected
    assert "private" not in error.message and "PRIVATE SQL" not in str(error)
    if expected == 422:
        assert error.message == "标签不存在"


@pytest.mark.parametrize("args", [(), (1062,), (1062, None), ("1062", "bad")])
def test_unknown_driver_error_shape_is_safe(args):
    error = IntegrityError("PRIVATE SQL", {}, Exception(*args))
    assert classify_write_error(error).status == 500


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("error", "expected"),
    [
        (db_error(1062, "private value for key 'uk_problems_slug'"), 409),
        (
            db_error(
                1452, "private CONSTRAINT 'fk_problem_tags_tag' FOREIGN KEY (tag_id)"
            ),
            422,
        ),
        (db_error(1062, "private value for key 'PRIMARY'"), 500),
    ],
)
async def test_link_failure_after_tag_precheck_rolls_back(error, expected):
    store = Store()
    store.failure, store.failure_error = "links", error
    with pytest.raises(AppError) as caught:
        await service(store).create_problem(ProblemCreate(**body()), **context())
    assert caught.value.status == expected
    assert store.problems == {} and store.links == {} and store.audits == []


@pytest.mark.anyio
@pytest.mark.parametrize("method", ["list_problems", "get_problem", "list_tags"])
@pytest.mark.parametrize(
    "error", [PoolTimeout(), OperationalError("SQL", {}, Exception())]
)
async def test_read_dependency_failure_is_safe_503(method, error):
    store = Store()
    store.failure, store.failure_error = "read", error
    svc = service(store)
    with pytest.raises(AppError) as caught:
        if method == "get_problem":
            await svc.get_problem(1)
        else:
            await getattr(svc, method)(page=1, size=20)
    assert caught.value.status == 503


@pytest.mark.anyio
async def test_repositories_use_projection_lock_refresh_and_never_commit():
    obj = problem()
    mapped = SimpleNamespace(mappings=lambda: SimpleNamespace(all=lambda: [{"id": 1}]))
    session = SimpleNamespace(
        scalar=AsyncMock(side_effect=[1, obj]),
        execute=AsyncMock(return_value=mapped),
        add=lambda row: None,
        flush=AsyncMock(),
        refresh=AsyncMock(),
    )
    repo = ProblemRepository(session)
    assert await repo.page(page=2, size=5) == ([{"id": 1}], 1)
    query = session.execute.call_args.args[0]
    sql = str(query.compile(dialect=mysql.dialect()))
    assert "description" not in sql and "ORDER BY problems.id DESC" in sql
    assert list(query.compile().params.values()) == [5, 5]
    assert await repo.lock_by_id(1) is obj
    query = session.scalar.call_args.args[0]
    assert query.get_execution_options()["populate_existing"] is True
    assert str(query.compile(dialect=mysql.dialect())).endswith("FOR UPDATE")
    result = await repo.create(created_by=1, **body_without_tags())
    assert result.status == "DRAFT" and result.created_by == 1
    await repo.update(
        obj, **{k: v for k, v in body_without_tags().items() if k != "slug"}
    )
    assert session.flush.await_count == 2 and session.refresh.await_count == 2
    assert not hasattr(session, "commit")


def body_without_tags():
    return {k: v for k, v in body().items() if k != "tag_ids"}


@pytest.mark.anyio
async def test_link_repository_flushes_replacement_and_tag_query_is_batched():
    added = []
    session = SimpleNamespace(
        execute=AsyncMock(return_value=SimpleNamespace(all=lambda: [(1, "tag")])),
        add_all=lambda rows: added.extend(rows),
        flush=AsyncMock(),
    )
    await ProblemRepository(session).replace_tags(1, [2, 3])
    assert [(row.problem_id, row.tag_id) for row in added] == [(1, 2), (1, 3)]
    assert session.flush.await_count == 1 and "DELETE FROM problem_tags" in str(
        session.execute.call_args.args[0]
    )
    tags = TagRepository(session)
    assert await tags.for_problems([]) == {}
    assert await tags.for_problems([1, 2]) == {1: ["tag"]}
    assert "JOIN tags" in str(session.execute.call_args.args[0])


def test_orm_matches_existing_mysql_table_shapes_and_constraints():
    assert set(Problem.__table__.columns.keys()) == {
        "id",
        "slug",
        "title",
        "description",
        "difficulty",
        "time_limit_ms",
        "memory_limit_mb",
        "status",
        "created_by",
        "created_at",
        "updated_at",
    }
    assert Problem.__table__.c.slug.type.length == 64
    assert Problem.__table__.c.title.type.length == 128
    assert isinstance(Problem.__table__.c.description.type, mysql.MEDIUMTEXT)
    assert Problem.__table__.c.time_limit_ms.type.unsigned
    assert str(Problem.__table__.c.status.server_default.arg) == "DRAFT"
    assert Tag.__table__.c.name.type.length == 32
    assert {c.name for c in ProblemTag.__table__.primary_key} == {
        "problem_id",
        "tag_id",
    }
    assert {f.name for f in ProblemTag.__table__.foreign_key_constraints} == {
        "fk_problem_tags_problem",
        "fk_problem_tags_tag",
    }
    for model in (Problem, Tag, ProblemTag):
        ddl = str(CreateTable(model.__table__).compile(dialect=mysql.dialect()))
        assert "utf8mb4_0900_ai_ci" in ddl
        assert model.__table__.c.id.type.unsigned if model is not ProblemTag else True
    assert "ON DELETE RESTRICT ON UPDATE RESTRICT" in str(
        CreateTable(Problem.__table__).compile(dialect=mysql.dialect())
    )
