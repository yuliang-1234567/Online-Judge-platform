import importlib
from contextlib import contextmanager

import asyncmy
import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr, ValidationError
from redis.asyncio.connection import Connection

from app.core.config import Settings
from app.main import create_app


def configured(**changes):
    values = {
        "database_url": "mysql+asyncmy://placeholder:placeholder@127.0.0.1:1/offline",
        "redis_url": "redis://127.0.0.1:1/4",
        "jwt_secret": "startup-only-key-with-at-least-32-bytes",
    }
    values.update(changes)
    return Settings(**values)


def test_module_import_does_not_read_environment(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("导入期禁止读取配置")

    with monkeypatch.context() as patch:
        patch.setattr(Settings, "__init__", forbidden)
        module = importlib.reload(importlib.import_module("app.main"))
        assert module.app is not None


def test_lifespan_and_healthz_construct_resources_without_connections(monkeypatch):
    async def forbidden(*args, **kwargs):
        raise AssertionError("离线启动和 healthz 不允许建立外部连接")

    monkeypatch.setattr(asyncmy, "connect", forbidden)
    monkeypatch.setattr(Connection, "connect", forbidden)
    with TestClient(create_app(configured())) as client:
        assert client.get("/healthz").json() == {"status": "ok"}


@contextmanager
def unwrap_runtime_error():
    try:
        yield
    except ExceptionGroup as group:
        # 不绑定 Starlette/AnyIO 是否包装异常，但必须存在原始认证配置错误。
        matched, remainder = group.split(RuntimeError)
        if matched is None or remainder is not None:
            raise
        raise matched.exceptions[0] from None


def test_missing_secret_fails_startup_before_healthz(monkeypatch, caplog):
    for key in [
        "JWT_SECRET",
        "DATABASE_URL",
        "REDIS_URL",
        "JWT_EXPIRE_MINUTES",
        "RATE_LIMIT_KEY_PREFIX",
    ]:
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv(
        "DATABASE_URL", "mysql+asyncmy://placeholder:private-marker@127.0.0.1:1/offline"
    )
    monkeypatch.setenv("REDIS_URL", "redis://:private-marker@127.0.0.1:1/4")
    with (
        pytest.raises(RuntimeError, match="认证配置错误") as error,
        unwrap_runtime_error(),
        TestClient(create_app()),
    ):
        pytest.fail("配置缺失时不应启动")
    assert "private-marker" not in str(error.value) + caplog.text


def test_settings_hide_secret_and_validate_before_resource_creation():
    settings = configured()
    assert isinstance(settings.jwt_secret, SecretStr)
    with pytest.raises(ValidationError):
        configured(jwt_secret="short")
    with pytest.raises(ValidationError) as error:
        configured(database_url="mysql+pymysql://user:private-marker@host/db")
    assert "private-marker" not in str(error.value)
    for prefix in ["", "oj:", "contains whitespace"]:
        with pytest.raises(ValidationError):
            configured(rate_limit_key_prefix=prefix)


def test_settings_do_not_use_integration_configuration_by_default(monkeypatch):
    monkeypatch.setenv("AUTH_INTEGRATION_DATABASE_URL", "invalid")
    monkeypatch.setenv("AUTH_INTEGRATION_REDIS_URL", "invalid")
    assert configured().rate_limit_key_prefix == "oj:ratelimit:auth"


def test_redis_async_retry_is_zero_and_awaits_failure_cleanup():
    from unittest.mock import AsyncMock

    from redis.exceptions import ConnectionError

    app = create_app(configured())
    with TestClient(app) as client:
        retry = app.state.rate_limiter.redis.connection_pool.connection_kwargs["retry"]
        operation = AsyncMock(side_effect=ConnectionError("offline-synthetic-error"))
        cleanup = AsyncMock()

        async def exercise():
            # 直接执行 Retry 协议；不借连接。同步 Retry 不会等待异步失败清理。
            with pytest.raises(ConnectionError):
                await retry.call_with_retry(operation, cleanup)

        client.portal.call(exercise)
        assert retry.get_retries() == 0
        operation.assert_awaited_once()
        cleanup.assert_awaited_once()


# 锁定已批准的 30–60 分钟边界，避免配置模型又退回模板曾写的 1–60。
@pytest.mark.parametrize(
    ("minutes", "accepted"), [(29, False), (30, True), (60, True), (61, False)]
)
def test_jwt_expiry_accepts_only_approved_range(minutes, accepted):
    if accepted:
        assert configured(jwt_expire_minutes=minutes).jwt_expire_minutes == minutes
    else:
        with pytest.raises(ValidationError) as error:
            configured(jwt_expire_minutes=minutes)
        assert error.value.errors()[0]["loc"] == ("jwt_expire_minutes",)
