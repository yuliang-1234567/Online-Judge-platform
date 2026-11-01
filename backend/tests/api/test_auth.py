from contextlib import asynccontextmanager
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Annotated
from unittest.mock import AsyncMock

import pytest
from argon2.exceptions import InvalidHashError, VerificationError
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.exc import IntegrityError, OperationalError, ProgrammingError
from sqlalchemy.exc import TimeoutError as SQLAlchemyTimeoutError

from app.api import deps
from app.api.v1.auth import router as auth_router
from app.core import http
from app.core.config import Settings
from app.core.db import get_session
from app.core.http import install_http_contract
from app.core.rate_limit import AuthRateLimiter
from app.core.security import create_access_token
from app.main import create_app
from app.services import auth as auth_service


class MemorySession:
    @asynccontextmanager
    async def begin(self):
        yield


class MemoryUsers:
    def __init__(self, session, rows):
        self.rows = rows

    async def create(self, username, password_hash):
        if username.lower() in self.rows:
            raise IntegrityError(
                "INSERT",
                {},
                Exception(1062, "Duplicate entry for key 'uk_users_username'"),
            )
        user = SimpleNamespace(
            id=len(self.rows) + 1,
            username=username,
            password_hash=password_hash,
            role="USER",
            status="ACTIVE",
            created_at=datetime.now(UTC),
        )
        self.rows[username.lower()] = user
        return user

    async def by_username(self, username):
        return self.rows.get(username.lower())

    async def by_id(self, user_id):
        return next((user for user in self.rows.values() if user.id == user_id), None)


class MemoryRedis:
    def __init__(self):
        self.counts = {}
        self.calls = []

    async def eval(self, script, number_keys, key, action, ttl):
        self.calls.append((key, action))
        if action == "consume":
            self.counts[key] = self.counts.get(key, 0) + 1
        return [self.counts.get(key, 0), ttl]


@pytest.fixture
def api(monkeypatch):
    rows = {}
    monkeypatch.setattr(http.logger, "disabled", False)
    settings = Settings(
        database_url="mysql+asyncmy://placeholder:placeholder@127.0.0.1:1/offline",
        redis_url="redis://127.0.0.1:1/4",
        jwt_secret="api-only-key-with-at-least-32-bytes",
    )
    app = create_app(settings)

    async def session():
        yield MemorySession()

    app.dependency_overrides[get_session] = session
    monkeypatch.setattr(
        deps, "UserRepository", lambda session: MemoryUsers(session, rows)
    )
    # 替换的是存储边界，路由、服务、真实哈希/JWT、鉴权和错误处理仍执行。
    # 内存排序/计数不是 MySQL collation 或 Redis Lua 的实库验证。
    with TestClient(app) as client:
        redis = MemoryRedis()
        app.state.rate_limiter = AuthRateLimiter(
            redis, "oj:ratelimit:auth-test:offline"
        )
        yield SimpleNamespace(app=app, client=client, rows=rows, redis=redis)


PASSWORD = "a-password-long-enough"


def register(api, username="alice"):
    return api.client.post(
        "/api/v1/auth/register", json={"username": username, "password": PASSWORD}
    )


def login(api, username="alice", password=PASSWORD):
    return api.client.post(
        "/api/v1/auth/login", json={"username": username, "password": password}
    )


def test_register_login_me_and_case_insensitive_duplicate(api):
    response = register(api)
    assert response.status_code == 201
    assert set(response.json()) == {"id", "username", "role", "status", "created_at"}
    assert response.json()["role"] == "USER"
    assert response.json()["created_at"].endswith("Z")
    duplicate = register(api, "ALICE")
    assert duplicate.status_code == 409
    assert duplicate.json()["error"]["code"] == "CONFLICT"
    token_response = login(api)
    assert token_response.status_code == 200
    assert set(token_response.json()) == {"access_token", "token_type", "expires_in"}
    assert token_response.json()["token_type"] == "bearer"
    assert token_response.json()["expires_in"] == 3600
    token = token_response.json()["access_token"]
    me = api.client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert me.status_code == 200
    assert me.json() == response.json()
    assert me.headers["x-request-id"]


def test_wrong_password_and_missing_user_are_indistinguishable(api):
    register(api)
    wrong = login(api, password="wrong")
    missing = login(api, username="nobody", password="wrong")
    assert wrong.status_code == missing.status_code == 401
    for result in [wrong, missing]:
        assert result.json()["error"]["code"] == "UNAUTHENTICATED"
        assert result.json()["error"]["message"] == "用户名或密码错误"


@pytest.mark.parametrize("header", [None, "Bearer malformed", "Basic secret"])
def test_no_or_bad_token_401(api, header):
    result = api.client.get(
        "/api/v1/auth/me", headers={"Authorization": header} if header else {}
    )
    assert result.status_code == 401
    assert result.json()["error"]["code"] == "UNAUTHENTICATED"


def test_same_token_is_rejected_after_disabling_user(api):
    register(api)
    token = login(api).json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}
    assert api.client.get("/api/v1/auth/me", headers=headers).status_code == 200
    api.rows["alice"].status = "DISABLED"
    response = api.client.get("/api/v1/auth/me", headers=headers)
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "FORBIDDEN"


def test_require_admin_dependency_contract_and_same_token_after_demotion(api):
    register(api)
    api.rows["alice"].role = "ADMIN"
    token = login(api).json()["access_token"]
    # 管理测试路由只存在于独立载体，不向生产 app 塞测试端点；仍执行真实鉴权依赖。
    carrier = FastAPI()
    install_http_contract(carrier)
    carrier.state.settings = api.app.state.settings
    carrier.dependency_overrides[get_session] = api.app.dependency_overrides[
        get_session
    ]

    @carrier.get("/guard")
    async def guard(user: Annotated[object, Depends(deps.require_admin)]):
        return {"allowed": True}

    headers = {"Authorization": f"Bearer {token}"}
    with TestClient(carrier) as client:
        assert client.get("/guard", headers=headers).status_code == 200
        api.rows["alice"].role = "USER"
        denied = client.get("/guard", headers=headers)
        assert denied.status_code == 403
        assert denied.json()["error"]["code"] == "FORBIDDEN"
    assert "/guard" not in api.app.openapi()["paths"]


@pytest.mark.parametrize(
    "body",
    [
        {"username": "中文名", "password": PASSWORD},
        {"username": "alice", "password": "short-secret"},
        {"username": "alice", "password": " " * 15},
        {"username": "alice", "password": PASSWORD, "role": "ADMIN"},
        {"username": "alice\n", "password": PASSWORD},
    ],
)
def test_422_never_echoes_password_or_raw_input(api, body, caplog):
    result = api.client.post("/api/v1/auth/register", json=body)
    assert result.status_code == 422
    assert result.json()["error"]["code"] == "VALIDATION_ERROR"
    assert body["password"] not in result.text
    assert body["password"] not in caplog.text
    assert not api.redis.calls


def test_logs_and_500_never_contain_password_token_or_hash(api, caplog):
    register(api)
    token = login(api).json()["access_token"]
    encoded = api.rows["alice"].password_hash
    api.rows["alice"].password_hash = "damaged-private-hash-marker"
    failed = login(api)
    assert failed.status_code == 500
    assert failed.json()["error"]["code"] == "INTERNAL_ERROR"
    assert "invalid_password_hash" in caplog.text
    for value in [
        PASSWORD,
        token,
        encoded,
        "damaged-private-hash-marker",
        "Authorization",
    ]:
        assert value not in failed.text
        assert value not in caplog.text


@pytest.mark.parametrize("error_type", [InvalidHashError, VerificationError])
def test_hash_internal_failures_are_sanitized_at_http_boundary(api, error_type, caplog):
    register(api)

    def fail(*args):
        raise error_type("sensitive-hash-raw-marker")

    api.app.state.passwords.hasher = SimpleNamespace(verify=fail)
    response = login(api)
    assert response.status_code == 500
    assert "sensitive-hash-raw-marker" not in response.text + caplog.text


def test_capacity_full_is_429_with_retry_after(api):
    ctx = api.app.state.passwords
    borrowers = [object(), object()]

    async def fill():
        for borrower in borrowers:
            ctx.limiter.acquire_on_behalf_of_nowait(borrower)

    async def release():
        for borrower in borrowers:
            ctx.limiter.release_on_behalf_of(borrower)

    api.client.portal.call(fill)
    try:
        response = login(api, username="nobody")
        assert response.status_code == 429
        assert response.headers["retry-after"] == "1"
        assert response.json()["error"]["code"] == "RATE_LIMITED"
    finally:
        api.client.portal.call(release)
    assert ctx.limiter.borrowed_tokens == 0


def test_fifth_failure_is_401_sixth_is_429_even_with_case_variant(api):
    for _ in range(5):
        assert login(api, username="nobody").status_code == 401
    response = login(api, username="NOBODY")
    assert response.status_code == 429
    assert response.headers["retry-after"] == "60"


def test_unicode_password_codepoints_not_bytes_and_no_normalization(api):
    password = "密" * 15
    result = api.client.post(
        "/api/v1/auth/register", json={"username": "unicode", "password": password}
    )
    assert result.status_code == 201
    assert login(api, username="unicode", password=password).status_code == 200


def test_request_id_contract_and_extra_fields_are_safe(api):
    response = api.client.post(
        "/api/v1/auth/register",
        json={"username": "alice", "password": PASSWORD, "private-field": "secret"},
        headers={"X-Request-ID": "offline-check"},
    )
    assert response.status_code == 422
    assert response.headers["x-request-id"] == "offline-check"
    assert response.json()["error"]["request_id"] == "offline-check"
    assert "secret" not in response.text
    assert "private-field" not in response.text


def test_invalid_login_username_is_422_before_limiter_or_hash(api):
    response = login(api, username="alice\n")
    assert response.status_code == 422
    assert not api.redis.calls


def test_deleted_user_with_valid_token_is_401(api):
    register(api)
    token = login(api).json()["access_token"]
    api.rows.clear()
    response = api.client.get(
        "/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"}
    )
    assert response.status_code == 401


def test_registration_sixth_attempt_is_429_and_redis_failure_is_503(api):
    from redis.exceptions import ConnectionError

    for index in range(5):
        assert register(api, f"user{index}").status_code == 201
    assert register(api, "sixth").status_code == 429

    async def unavailable(*args):
        raise ConnectionError("sensitive-redis-connection-marker")

    api.redis.eval = unavailable
    response = register(api, "seventh")
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "SERVICE_UNAVAILABLE"
    assert "sensitive-redis-connection-marker" not in response.text


# 用真实路由、服务、仓储与 get_session，只替换会话工厂的数据库边界。
# 故障点覆盖写入/提交及两条查询路径；事件证明清理调用，不能证明实库回滚。
@pytest.mark.parametrize(
    ("route", "stage"),
    [
        ("register", "flush"),
        ("register", "refresh"),
        ("register", "commit"),
        ("login", "query"),
        ("me", "query"),
    ],
)
@pytest.mark.parametrize(
    ("error_type", "status", "code", "message"),
    [
        (SQLAlchemyTimeoutError, 503, "SERVICE_UNAVAILABLE", "认证服务暂时不可用"),
        (OperationalError, 503, "SERVICE_UNAVAILABLE", "认证服务暂时不可用"),
        (ProgrammingError, 500, "INTERNAL_ERROR", "服务内部错误"),
    ],
)
def test_database_failures_map_and_close_session_without_leaks(
    monkeypatch, caplog, route, stage, error_type, status, code, message
):
    import socket

    events = []
    attempts = []
    marker = "private-db-error-marker"
    encoded = "private-db-hash-marker"
    settings = Settings(
        database_url="mysql+asyncmy://placeholder:placeholder@127.0.0.1:1/offline",
        redis_url="redis://127.0.0.1:1/4",
        jwt_secret="db-failure-test-key-with-at-least-32-bytes",
    )
    token = create_access_token(1, settings=settings)

    def no_network(*args, **kwargs):
        attempts.append("blocked")
        raise AssertionError("数据库故障测试禁止建立连接")

    monkeypatch.setattr(socket.socket, "connect", no_network)
    monkeypatch.setattr(socket, "getaddrinfo", no_network)
    monkeypatch.setattr(http.logger, "disabled", False)

    def checkpoint(point):
        events.append(point)
        if point == stage:
            if error_type is SQLAlchemyTimeoutError:
                raise error_type(marker)
            raise error_type(
                "SELECT private_statement", {"password": marker}, Exception(marker)
            )

    class FailingSession:
        async def __aenter__(self):
            events.append("session_enter")
            return self

        async def __aexit__(self, *args):
            events.append("session_close")

        @asynccontextmanager
        async def begin(self):
            events.append("begin")
            try:
                yield
                checkpoint("commit")
            except Exception:
                events.append("rollback")
                raise

        def add(self, user):
            events.append("add")

        async def flush(self):
            checkpoint("flush")

        async def refresh(self, user):
            checkpoint("refresh")

        async def scalar(self, statement):
            checkpoint("query")

    # 独立 app 不跑生产 lifespan；真实依赖仍从 app.state 取得工厂并关闭会话。
    # 不替换 get_session 或 UserRepository，防止测试绕过本次要保护的异常边界。
    app = FastAPI()
    install_http_contract(app)
    app.include_router(auth_router)
    app.state.settings = settings
    app.state.session_factory = FailingSession
    app.state.passwords = object()
    app.state.rate_limiter = AsyncMock()

    async def hash_without_work(*args, **kwargs):
        events.append("hash")
        return encoded

    monkeypatch.setattr(auth_service, "hash_password", hash_without_work)
    with TestClient(app) as client:
        if route == "me":
            response = client.get(
                "/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"}
            )
        else:
            response = client.post(
                f"/api/v1/auth/{route}",
                json={"username": "alice", "password": PASSWORD},
            )

    assert response.status_code == status
    assert response.json() == {
        "error": {
            "code": code,
            "message": message,
            "request_id": response.headers["x-request-id"],
        }
    }
    assert events.count("session_enter") == events.count("session_close") == 1
    assert events.count("rollback") == 1
    assert events[-2:] == ["rollback", "session_close"]
    assert events.count(stage) == 1
    if route == "register":
        assert events.index("hash") < events.index("begin")
    if stage != "commit":
        assert "commit" not in events
    if status == 500:
        assert "request_failed" in caplog.text
    for value in [
        marker,
        encoded,
        PASSWORD,
        token,
        "private_statement",
        "Authorization",
    ]:
        assert value not in response.text + caplog.text
    assert attempts == []
