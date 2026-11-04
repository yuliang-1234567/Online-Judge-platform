import asyncio
import json
from contextlib import asynccontextmanager
from copy import deepcopy
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy.dialects import mysql
from sqlalchemy.exc import OperationalError
from sqlalchemy.exc import TimeoutError as SQLAlchemyTimeoutError

from app.core.http import AppError
from app.models.audit_log import AuditLog
from app.models.user import User
from app.repositories.audit_log import AuditLogRepository
from app.repositories.user import UserRepository
from app.schemas.admin import UserPatch
from app.services.admin import AdminService, normalize_ip, summarize_access


@pytest.fixture
def anyio_backend():
    return "asyncio"


def user(user_id, role="ADMIN", status="ACTIVE"):
    return User(
        id=user_id,
        username=f"user_{user_id}",
        password_hash="private-unit-hash",
        role=role,
        status=status,
        created_at=datetime(2026, 11, 3, tzinfo=UTC),
    )


# 事务替身只在 commit 发布暂存状态，flush 留在事务内；并发锁由 asyncio 模拟。
# 这些断言证明服务的协议与回滚责任，不能代替真实 InnoDB 锁/隔离级别验收。
class Store:
    def __init__(self, rows):
        self.rows = {row.id: row for row in rows}
        self.audits = []
        self.lock = asyncio.Lock()
        self.locked = asyncio.Event()
        self.waiting = asyncio.Event()
        self.resume = asyncio.Event()
        self.pause_first = False


class Transaction:
    def __init__(self, store):
        self.store = store
        self.events = []
        self.pending = {}
        self.audits = []
        self.owns_lock = False

    @asynccontextmanager
    async def begin(self):
        self.events.append("begin")
        try:
            yield
            self.store.rows.update(self.pending)
            self.store.audits.extend(self.audits)
            self.events.append("commit")
        except BaseException:
            self.events.append("rollback")
            raise
        finally:
            if self.owns_lock:
                self.store.lock.release()


class Users:
    def __init__(self, tx):
        self.tx = tx

    async def lock_active_admin_ids(self):
        self.tx.events.append("admin_lock")
        store = self.tx.store
        if store.lock.locked():
            store.waiting.set()
        await store.lock.acquire()
        self.tx.owns_lock = True
        if store.pause_first:
            store.pause_first = False
            store.locked.set()
            await store.resume.wait()
        return sorted(
            key
            for key, row in store.rows.items()
            if (row.role, row.status) == ("ADMIN", "ACTIVE")
        )

    async def lock_by_id(self, user_id):
        self.tx.events.append("target_lock")
        return deepcopy(self.tx.store.rows.get(user_id))

    async def update_access(self, target, *, role, status):
        target.role, target.status = role, status
        self.tx.pending[target.id] = target
        self.tx.events.append("user_flush")


class Audits:
    def __init__(self, tx, failure=None):
        self.tx, self.failure = tx, failure

    async def append(self, **summary):
        self.tx.events.append("audit_flush")
        if self.failure:
            raise self.failure
        self.tx.audits.append(summary)


def service(store, failure=None):
    tx = Transaction(store)
    return AdminService(tx, Users(tx), Audits(tx, failure)), tx


async def patch(svc, target, **values):
    return await svc.patch_user(
        target,
        UserPatch(**values),
        actor_id=1,
        request_id="offline-request",
        ip="2001:0db8:0000:0000:0000:0000:0000:0001",
    )


@pytest.mark.anyio
@pytest.mark.parametrize("order", [(1, 2), (2, 1)])
async def test_overlapping_removals_only_one_commits_in_both_orders(order):
    store = Store([user(1), user(2)])
    store.pause_first = True
    first, first_tx = service(store)
    second, second_tx = service(store)
    task1 = asyncio.create_task(patch(first, order[0], status="DISABLED"))
    await asyncio.wait_for(store.locked.wait(), 1)
    task2 = asyncio.create_task(patch(second, order[1], role="USER"))
    try:
        await asyncio.wait_for(store.waiting.wait(), 1)
        store.resume.set()
        # 超时/死锁直接令测试失败，不能被解释成业务 409。
        results = await asyncio.wait_for(
            asyncio.gather(task1, task2, return_exceptions=True), 1
        )
    finally:
        store.resume.set()
        for task in (task1, task2):
            if not task.done():
                task.cancel()
        await asyncio.gather(task1, task2, return_exceptions=True)
    assert results[0].id == order[0]
    assert isinstance(results[1], AppError) and results[1].status == 409
    assert (
        sum(
            (row.role, row.status) == ("ADMIN", "ACTIVE") for row in store.rows.values()
        )
        == 1
    )
    assert len(store.audits) == 1
    assert first_tx.events == [
        "begin",
        "admin_lock",
        "target_lock",
        "user_flush",
        "audit_flush",
        "commit",
    ]
    assert second_tx.events == ["begin", "admin_lock", "target_lock", "rollback"]


@pytest.mark.anyio
@pytest.mark.parametrize(
    "values",
    [
        {"role": "USER"},
        {"status": "DISABLED"},
        {"role": "USER", "status": "ACTIVE"},
        {"role": "ADMIN", "status": "DISABLED"},
    ],
)
async def test_last_admin_rejection_leaves_user_and_audit_unchanged(values):
    store = Store([user(1)])
    svc, tx = service(store)
    with pytest.raises(AppError) as error:
        await patch(svc, 1, **values)
    assert error.value.status == 409
    assert (store.rows[1].role, store.rows[1].status) == ("ADMIN", "ACTIVE")
    assert store.audits == []
    assert tx.events == ["begin", "admin_lock", "target_lock", "rollback"]


@pytest.mark.anyio
@pytest.mark.parametrize(
    "failure",
    [
        RuntimeError("private-audit-failure"),
        OperationalError("INSERT", {}, Exception("private-db-failure")),
    ],
)
async def test_audit_failure_rolls_back_already_flushed_access_changes(failure):
    store = Store([user(1), user(2)])
    svc, tx = service(store, failure)
    with pytest.raises((RuntimeError, AppError)) as error:
        await patch(svc, 2, role="USER", status="DISABLED")
    if isinstance(error.value, AppError):
        assert error.value.status == 503
        assert "private-" not in error.value.message
    assert (store.rows[2].role, store.rows[2].status) == ("ADMIN", "ACTIVE")
    assert store.audits == []
    assert tx.events[-3:] == ["user_flush", "audit_flush", "rollback"]


@pytest.mark.anyio
@pytest.mark.parametrize(
    "values",
    [
        {"role": "ADMIN"},
        {"status": "ACTIVE"},
        {"role": "ADMIN", "status": "ACTIVE"},
    ],
)
async def test_pure_promotion_or_activation_skips_collection_guard(values):
    store = Store([user(1), user(2, "USER", "DISABLED")])
    svc, tx = service(store)
    await patch(svc, 2, **values)
    assert "admin_lock" not in tx.events
    assert tx.events == ["begin", "target_lock", "user_flush", "audit_flush", "commit"]
    assert store.audits[0]["ip"] == "2001:db8::1"


@pytest.mark.anyio
async def test_target_missing_returns_404_without_writes():
    store = Store([user(1)])
    svc, tx = service(store)
    with pytest.raises(AppError) as error:
        await patch(svc, 99, role="USER")
    assert error.value.status == 404
    assert store.audits == [] and tx.pending == {}


@pytest.mark.anyio
async def test_active_admin_query_is_ordered_locking_read_and_target_is_refreshed():
    session = SimpleNamespace(
        scalars=AsyncMock(return_value=SimpleNamespace(all=lambda: [1, 2])),
        scalar=AsyncMock(return_value=user(2)),
    )
    repo = UserRepository(session)
    assert await repo.lock_active_admin_ids() == [1, 2]
    statement = session.scalars.call_args.args[0]
    sql = str(
        statement.compile(
            dialect=mysql.dialect(), compile_kwargs={"literal_binds": True}
        )
    )
    assert " ".join(sql.split()) == (
        "SELECT users.id FROM users WHERE users.`role` = 'ADMIN' "
        "AND users.status = 'ACTIVE' ORDER BY users.id FOR UPDATE"
    )
    await repo.lock_by_id(2)
    statement = session.scalar.call_args.args[0]
    assert statement.get_execution_options()["populate_existing"] is True
    assert str(statement.compile(dialect=mysql.dialect())).endswith("FOR UPDATE")


@pytest.mark.anyio
async def test_username_search_escapes_like_and_uses_bound_pagination():
    session = SimpleNamespace(
        scalar=AsyncMock(return_value=1),
        scalars=AsyncMock(return_value=SimpleNamespace(all=lambda: [user(1)])),
    )
    rows, total = await UserRepository(session).page(page=2, size=5, username="a_%")
    assert [row.id for row in rows] == [1] and total == 1
    count_query = session.scalar.call_args.args[0].compile(dialect=mysql.dialect())
    query = session.scalars.call_args.args[0].compile(dialect=mysql.dialect())
    assert "a/_/%" in query.params.values()
    assert "a/_/%" in count_query.params.values()
    assert "a_%" not in str(query)
    assert "ORDER BY users.id DESC" in str(query) and "ESCAPE" in str(query)
    assert list(query.params.values()).count(5) == 2


@pytest.mark.anyio
async def test_audit_repository_flushes_without_commit_and_uses_exclusive_cursor():
    session = SimpleNamespace(
        add=lambda row: added.append(row),
        flush=AsyncMock(),
        scalars=AsyncMock(return_value=SimpleNamespace(all=lambda: [])),
    )
    added = []
    repo = AuditLogRepository(session)
    await repo.append(
        user_id=1,
        action="UPDATE_USER",
        resource_type="USER",
        resource_id=2,
        payload_summary="safe-summary",
        request_id="request",
        ip="127.0.0.1",
    )
    assert isinstance(added[0], AuditLog) and added[0].payload_summary == "safe-summary"
    session.flush.assert_awaited_once()
    assert await repo.before(9, 2) == []
    query = session.scalars.call_args.args[0].compile(dialect=mysql.dialect())
    assert "audit_logs.id <" in str(query) and "ORDER BY audit_logs.id DESC" in str(
        query
    )
    assert 9 in query.params.values() and 3 in query.params.values()


def test_audit_mapping_matches_existing_columns_indexes_and_foreign_key():
    table = AuditLog.__table__
    assert list(table.columns.keys()) == [
        "id",
        "user_id",
        "action",
        "resource_type",
        "resource_id",
        "payload_summary",
        "request_id",
        "ip",
        "created_at",
    ]
    assert {
        index.name: tuple(c.name for c in index.columns) for index in table.indexes
    } == {
        "idx_audit_logs_resource": ("resource_type", "resource_id", "id"),
        "idx_audit_logs_user": ("user_id", "id"),
    }
    fk = next(iter(table.c.user_id.foreign_keys))
    assert (fk.target_fullname, fk.ondelete, fk.onupdate) == (
        "users.id",
        "RESTRICT",
        "RESTRICT",
    )
    assert table.c.payload_summary.type.length == 2048
    assert table.c.created_at.type.fsp == 3
    assert table.c.payload_summary.nullable and not table.c.user_id.nullable


def test_summary_uses_only_access_fields_then_truncates_characters():
    target = user(2, "USER", "DISABLED")
    summary = summarize_access(("ADMIN", "ACTIVE"), target)
    assert json.loads(summary) == {
        "before": {"role": "ADMIN", "status": "ACTIVE"},
        "after": {"role": "USER", "status": "DISABLED"},
    }
    assert "password" not in summary and target.password_hash not in summary
    # 合成超长字段仅用于验证字符边界，不表示 API 接受这种角色值。
    target.role = "角" * 3000
    summary = summarize_access(("ADMIN", "ACTIVE"), target)
    assert len(summary) == 2048 and len(summary.encode("utf-8")) > 2048


@pytest.mark.parametrize(
    ("ip", "expected"),
    [
        ("2001:0db8:0:0:0:0:0:1", "2001:db8::1"),
        ("127.0.0.1", "127.0.0.1"),
        (None, "unknown"),
        ("bad-peer", "unknown"),
    ],
)
def test_ip_is_normalized_or_explicitly_unknown(ip, expected):
    assert normalize_ip(ip) == expected


@pytest.mark.anyio
@pytest.mark.parametrize("method", ["list_users", "list_audits"])
async def test_read_pool_timeout_is_safe_503(method):
    tx = Transaction(Store([]))
    repo = SimpleNamespace(
        page=AsyncMock(side_effect=SQLAlchemyTimeoutError("private-timeout")),
        before=AsyncMock(side_effect=SQLAlchemyTimeoutError("private-timeout")),
    )
    svc = AdminService(tx, repo, repo)
    kwargs = (
        {"page": 1, "size": 20, "username": None}
        if method == "list_users"
        else {"cursor": None, "limit": 20}
    )
    with pytest.raises(AppError) as error:
        await getattr(svc, method)(**kwargs)
    assert error.value.status == 503
    assert "private-" not in error.value.message
    assert tx.events[-1] == "rollback"


@pytest.mark.anyio
async def test_access_repository_flushes_and_refreshes_without_commit():
    session = SimpleNamespace(flush=AsyncMock(), refresh=AsyncMock())
    target = user(2)
    await UserRepository(session).update_access(target, role="USER", status="DISABLED")
    assert (target.role, target.status) == ("USER", "DISABLED")
    session.flush.assert_awaited_once()
    session.refresh.assert_awaited_once_with(target)
