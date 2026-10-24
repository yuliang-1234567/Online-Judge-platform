"""ASGI application and process liveness endpoint."""

from fastapi import FastAPI

# uvicorn app.main:app 从这里取得 ASGI 应用，路由注册在同一个实例上。
app = FastAPI(title="OJ Platform", version="0.1.0")


# 存活检查只证明进程能响应；加入数据库/Redis 查询会把依赖故障混成进程故障。
@app.get("/healthz", tags=["operations"])
async def healthz() -> dict[str, str]:
    """Report process liveness without checking external dependencies."""
    return {"status": "ok"}
