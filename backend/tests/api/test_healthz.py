from fastapi.testclient import TestClient

from app.main import app


def test_healthz_returns_process_liveness() -> None:
    # TestClient 在本进程调用 ASGI 应用，无须启动 HTTP 服务，也不应依赖数据库。
    with TestClient(app) as client:
        response = client.get("/healthz")

    # 同时约束状态码、媒体类型和响应体；这是存活接口契约，不是依赖服务就绪证明。
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/json"
    assert response.json() == {"status": "ok"}
