import asyncmy
from fastapi.testclient import TestClient
from redis.asyncio.connection import Connection

from app.core.config import Settings
from app.main import create_app


def test_healthz_returns_process_liveness(monkeypatch) -> None:
    async def forbidden(*args, **kwargs):
        raise AssertionError("存活检查不得连接依赖")

    monkeypatch.setattr(asyncmy, "connect", forbidden)
    monkeypatch.setattr(Connection, "connect", forbidden)
    test_settings = Settings(
        database_url="mysql+asyncmy://placeholder:placeholder@127.0.0.1:1/offline",
        redis_url="redis://127.0.0.1:1/4",
        jwt_secret="healthz-only-key-with-at-least-32-bytes",
    )
    # 显式注入测试配置，CI 不需真实凭据；TestClient 仍运行真实 lifespan。
    with TestClient(create_app(test_settings)) as client:
        response = client.get("/healthz")
    # 响应只证明进程存活，不能推出数据库/Redis 已就绪。
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/json"
    assert response.json() == {"status": "ok"}
