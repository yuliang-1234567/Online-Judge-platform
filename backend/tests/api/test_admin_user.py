import json
import socket
from contextlib import asynccontextmanager
from copy import deepcopy
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app.api import deps
from app.core.config import Settings
from app.core.db import get_session
from app.core.security import create_access_token
from app.main import create_app
from app.models.user import User


# HTTP 用真实生产路由、JWT、权限、管理服务与错误处理；只替换存储边界。
# 此处的内存事务不是数据库锁或持久化证据。
class MemorySession:
    def __init__(self, store):
        self.store = store
        self.changed = False

    @asynccontextmanager
    async def begin(self):
        self.rows = deepcopy(self.store.rows)
        self.pending_audits = []
        self.changed = False
        yield
        if self.changed:
            self.store.rows = self.rows
            self.store.audits.extend(self.pending_audits)


class MemoryUsers:
    def __init__(self, session):
        self.session = session

    async def by_id(self, user_id):
        self.session.store.auth_reads.append(user_id)
        return self.session.rows.get(user_id)

    async def page(self, *, page, size, username):
        rows = sorted(self.session.rows.values(), key=lambda row: row.id, reverse=True)
        if username:
            rows = [row for row in rows if username.lower() in row.username.lower()]
        start = (page - 1) * size
        return rows[start : start + size], len(rows)

    async def lock_active_admin_ids(self):
        return sorted(
            row.id
            for row in self.session.rows.values()
            if (row.role, row.status) == ("ADMIN", "ACTIVE")
        )

    async def lock_by_id(self, user_id):
        return self.session.rows.get(user_id)

    async def update_access(self, target, *, role, status):
        target.role, target.status = role, status
        self.session.changed = True


class MemoryAudits:
    def __init__(self, session):
        self.session = session

    async def append(self, **values):
        if self.session.store.audit_failure:
            raise RuntimeError("private-raw-body-marker")
        self.session.pending_audits.append(
            SimpleNamespace(
                id=len(self.session.store.audits) + 1,
                created_at=datetime(2026, 11, 3, 8, 0, 0, 123000),
                **values,
            )
        )

    async def before(self, cursor, limit):
        rows = sorted(self.session.store.audits, key=lambda row: row.id, reverse=True)
        return [row for row in rows if cursor is None or row.id < cursor][: limit + 1]


def make_user(user_id, role="USER", status="ACTIVE", username=None):
    return User(
        id=user_id,
        username=username or f"member_{user_id}",
        password_hash="private-api-hash-marker",
        role=role,
        status=status,
        created_at=datetime(2026, 11, 3, 8, 0, 0, 123000, tzinfo=UTC),
    )


@pytest.fixture
def api(monkeypatch):
    def no_network(*args, **kwargs):
        raise AssertionError("offline admin tests must not connect to services")

    monkeypatch.setattr(socket.socket, "connect", no_network)
    settings = Settings(
        database_url="mysql+asyncmy://placeholder:placeholder@127.0.0.1:1/offline",
        redis_url="redis://127.0.0.1:1/4",
        jwt_secret="offline-admin-key-with-at-least-32-bytes",
    )
    store = SimpleNamespace(
        rows={
            row.id: row
            for row in [
                make_user(1, "ADMIN"),
                make_user(2),
                make_user(3),
                make_user(4, "ADMIN", "DISABLED"),
            ]
        },
        audits=[],
        auth_reads=[],
        audit_failure=False,
    )
    app = create_app(settings)
    # 仅注入本测试需要的状态，不运行会创建外部资源客户端的 lifespan。
    app.state.settings = settings

    async def session():
        yield MemorySession(store)

    app.dependency_overrides[get_session] = session
    monkeypatch.setattr(deps, "UserRepository", MemoryUsers)
    monkeypatch.setattr(deps, "AuditLogRepository", MemoryAudits)
    client = TestClient(app, client=("2001:0db8:0:0:0:0:0:1", 5000))

    def headers(user_id=1):
        return {
            "Authorization": f"Bearer {create_access_token(user_id, settings=settings)}"
        }

    try:
        yield SimpleNamespace(client=client, store=store, headers=headers, app=app)
    finally:
        client.close()


ROUTES = [
    ("GET", "/api/v1/admin/users"),
    ("PATCH", "/api/v1/admin/users/2"),
    ("GET", "/api/v1/admin/audit-logs"),
]


@pytest.mark.parametrize(("method", "path"), ROUTES)
@pytest.mark.parametrize(
    "authorization", [None, "Bearer malformed", "Basic private-token"]
)
def test_all_admin_routes_require_valid_identity(api, method, path, authorization):
    response = api.client.request(
        method,
        path,
        headers={"Authorization": authorization} if authorization else {},
        json={"role": "ADMIN"} if method == "PATCH" else None,
    )
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "UNAUTHENTICATED"
    assert response.headers["WWW-Authenticate"] == "Bearer"
    assert api.store.audits == []


@pytest.mark.parametrize(("method", "path"), ROUTES)
@pytest.mark.parametrize("user_id", [3, 4])
def test_all_admin_routes_reject_regular_or_disabled_user(api, method, path, user_id):
    response = api.client.request(
        method,
        path,
        headers=api.headers(user_id),
        json={"role": "ADMIN"} if method == "PATCH" else None,
    )
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "FORBIDDEN"
    assert api.store.audits == []


@pytest.mark.parametrize(
    "body",
    [
        {},
        {"role": None},
        {"status": None},
        {"role": "ROOT"},
        {"status": "BANNED"},
        {"role": "admin"},
        {"role": 1},
        {"username": "hijacked"},
        {"role": "ADMIN", "status": None},
        {"role": "ADMIN", "password_hash": "private-hash"},
    ],
)
def test_patch_rejects_empty_null_unknown_or_invalid_fields(api, body):
    response = api.client.patch(
        "/api/v1/admin/users/2", headers=api.headers(), json=body
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"
    assert api.store.rows[2].role == "USER" and not api.store.audits


def test_admin_validation_response_and_logs_do_not_echo_password_or_raw_body(
    api, caplog
):
    body = (
        '{"role":"ROOT","password":"private-body-password",'
        '"raw":"private-raw-body-marker"}'
    )
    response = api.client.patch(
        "/api/v1/admin/users/2",
        headers={**api.headers(), "Content-Type": "application/json"},
        content=body,
    )
    assert response.status_code == 422
    assert response.json()["error"]["message"] == "请求参数不合法：role"
    for forbidden in [
        "password",
        "private-body-password",
        "private-raw-body-marker",
        body,
    ]:
        assert forbidden not in response.text
        assert forbidden not in caplog.text


def test_patch_commits_safe_audit_and_reuses_admin_dependency_result(api):
    response = api.client.patch(
        "/api/v1/admin/users/2",
        headers={
            **api.headers(),
            "X-Request-ID": "admin-request",
            "X-Forwarded-For": "192.0.2.9",
        },
        json={"role": "ADMIN"},
    )
    assert response.status_code == 200
    assert set(response.json()) == {"id", "username", "role", "status", "created_at"}
    assert response.json()["created_at"] == "2026-11-03T08:00:00.123Z"
    assert api.store.auth_reads == [1]
    assert api.store.rows[2].role == "ADMIN"
    audit = api.store.audits[0]
    assert (audit.user_id, audit.action, audit.resource_type, audit.resource_id) == (
        1,
        "UPDATE_USER",
        "USER",
        2,
    )
    assert audit.request_id == response.headers["X-Request-ID"] == "admin-request"
    assert audit.ip == "2001:db8::1"
    assert json.loads(audit.payload_summary) == {
        "before": {"role": "USER", "status": "ACTIVE"},
        "after": {"role": "ADMIN", "status": "ACTIVE"},
    }
    assert "password" not in audit.payload_summary


@pytest.mark.parametrize(("target", "expected"), [(999, 404), (1, 409)])
def test_missing_target_and_last_admin_protection_do_not_write(api, target, expected):
    response = api.client.patch(
        f"/api/v1/admin/users/{target}",
        headers=api.headers(),
        json={"role": "USER"},
    )
    assert response.status_code == expected
    assert response.json()["error"]["code"] == (
        "NOT_FOUND" if expected == 404 else "CONFLICT"
    )
    assert api.store.rows[1].role == "ADMIN" and api.store.audits == []


def test_audit_failure_returns_safe_500_and_rolls_back_user(api, caplog):
    api.store.audit_failure = True
    response = api.client.patch(
        "/api/v1/admin/users/2",
        headers=api.headers(),
        json={"role": "ADMIN"},
    )
    assert response.status_code == 500
    assert response.json()["error"]["code"] == "INTERNAL_ERROR"
    assert "private-raw-body-marker" not in response.text + caplog.text
    assert "request_failed" in caplog.text
    assert api.store.rows[2].role == "USER" and api.store.audits == []


def test_same_token_uses_current_role_and_status_on_next_request(api):
    api.store.rows[2].role = "ADMIN"
    token2 = api.headers(2)
    assert api.client.get("/api/v1/admin/users", headers=token2).status_code == 200
    assert (
        api.client.patch(
            "/api/v1/admin/users/2", headers=api.headers(), json={"role": "USER"}
        ).status_code
        == 200
    )
    assert api.client.get("/api/v1/admin/users", headers=token2).status_code == 403
    me = api.client.get("/api/v1/auth/me", headers=token2)
    assert me.status_code == 200 and me.json()["role"] == "USER"
    assert (
        api.client.patch(
            "/api/v1/admin/users/2", headers=api.headers(), json={"status": "DISABLED"}
        ).status_code
        == 200
    )
    assert api.client.get("/api/v1/auth/me", headers=token2).status_code == 403


def test_users_search_page_and_size_do_not_expose_password_hash(api):
    response = api.client.get(
        "/api/v1/admin/users",
        headers=api.headers(),
        params={"page": 2, "size": 1, "username": "MEMBER_"},
    )
    assert response.status_code == 200
    data = response.json()
    assert (data["page"], data["size"], data["total"]) == (2, 1, 4)
    assert [row["id"] for row in data["items"]] == [3]
    assert (
        "password" not in response.text
        and "private-api-hash-marker" not in response.text
    )
    assert api.store.audits == []


def test_audit_cursor_has_no_duplicates_and_null_when_exhausted(api):
    for body in [{"role": "ADMIN"}, {"status": "DISABLED"}, {"status": "ACTIVE"}]:
        assert (
            api.client.patch(
                "/api/v1/admin/users/2", headers=api.headers(), json=body
            ).status_code
            == 200
        )

    def page(**params):
        response = api.client.get(
            "/api/v1/admin/audit-logs", headers=api.headers(), params=params
        )
        assert response.status_code == 200
        return response.json()

    first = page(limit=2)
    assert [row["id"] for row in first["items"]] == [3, 2]
    assert first["next_cursor"] == 2
    second = page(limit=2, cursor=first["next_cursor"])
    assert [row["id"] for row in second["items"]] == [1]
    assert second["next_cursor"] is None
    assert page(limit=3)["next_cursor"] is None
    assert page(cursor=1) == {"items": [], "next_cursor": None}
    assert first["items"][0]["created_at"] == "2026-11-03T08:00:00.123Z"


@pytest.mark.parametrize(
    ("path", "params"),
    [
        ("users", {"size": 51}),
        ("users", {"size": 0}),
        ("users", {"page": 0}),
        ("users", {"username": "x" * 33}),
        ("audit-logs", {"limit": 101}),
        ("audit-logs", {"limit": 0}),
        ("audit-logs", {"cursor": 0}),
        ("audit-logs", {"cursor": -1}),
    ],
)
def test_list_input_bounds_are_422(api, path, params):
    response = api.client.get(
        f"/api/v1/admin/{path}", headers=api.headers(), params=params
    )
    assert response.status_code == 422
    assert api.store.audits == []


def test_admin_openapi_paths_match_design(api):
    paths = api.app.openapi()["paths"]
    assert "get" in paths["/api/v1/admin/users"]
    assert "patch" in paths["/api/v1/admin/users/{id}"]
    assert "get" in paths["/api/v1/admin/audit-logs"]
