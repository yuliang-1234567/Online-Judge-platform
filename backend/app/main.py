"""ASGI application and process liveness endpoint."""

from contextlib import AsyncExitStack, asynccontextmanager

from fastapi import FastAPI
from pydantic import ValidationError
from redis.asyncio import Redis
from redis.asyncio.retry import Retry
from redis.backoff import NoBackoff

from app.api.v1.auth import router
from app.core.config import Settings
from app.core.db import create_database
from app.core.http import install_http_contract
from app.core.rate_limit import AuthRateLimiter
from app.core.security import build_password_context


# 工厂可注入测试配置，生产 app.main:app 则在 lifespan 才读取环境；导入不能触发依赖连接。
# 路由和错误契约在创建时注册，资源在启动成功后共享，不能把请求级会话存进 app.state。
def create_app(settings: Settings | None = None) -> FastAPI:
    # yield 前为启动、后为退出；配置错误必须阻止启动，
    # 不能用可用的 healthz 掩盖配置缺失。
    @asynccontextmanager
    async def lifespan(application: FastAPI):
        try:
            configured = settings if settings is not None else Settings()
        except (ValidationError, ValueError):
            # 不能把包含配置输入的 ValidationError 透传给启动日志。
            raise RuntimeError("认证配置错误") from None
        # 每创建一个资源立即登记关闭：后续初始化失败也会释放已登记资源。
        # 回调逆序运行，先关 Redis 再 dispose 引擎；正常关闭与启动中途异常走同一出口。
        async with AsyncExitStack() as resources:
            engine, sessions = create_database(configured)
            resources.push_async_callback(engine.dispose)
            redis = Redis.from_url(
                configured.redis_url.get_secret_value(),
                socket_connect_timeout=1,
                socket_timeout=1,
                retry=Retry(NoBackoff(), 0),
            )
            resources.push_async_callback(redis.aclose)
            application.state.settings = configured
            application.state.session_factory = sessions
            application.state.rate_limiter = AuthRateLimiter(
                redis, configured.rate_limit_key_prefix
            )
            # 每应用实例只建一次密码上下文，让所有请求的真实/dummy 工作共享两槽准入。
            application.state.passwords = await build_password_context()
            # 引擎与 Redis 客户端均惰性取连接；启动不探活依赖，healthz 只看进程。
            yield

    application = FastAPI(title="OJ Platform", version="0.1.0", lifespan=lifespan)
    install_http_contract(application)
    application.include_router(router)

    @application.get("/healthz", tags=["operations"])
    async def healthz() -> dict[str, str]:
        """Report process liveness without checking external dependencies."""
        return {"status": "ok"}

    return application


# 导入时只注册路由；环境在 lifespan 读取，测试可显式注入 Settings，避免依赖真实配置。
app = create_app()
