from collections.abc import AsyncIterator

from fastapi import Request
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.config import Settings


# lifespan 拿到引擎及会话工厂并登记 dispose；
# 这里不建表、不运行迁移、不探测数据库可用性。
def create_database(
    settings: Settings,
) -> tuple[AsyncEngine, async_sessionmaker[AsyncSession]]:
    # 创建引擎不取连接；pre_ping 在真正借出连接时检测失效连接，healthz 不会触发它。
    engine = create_async_engine(
        settings.database_url.get_secret_value(),
        pool_pre_ping=True,
        # 隐藏 SQL 参数不等于 URL 可随意打印；
        # 连接初始化统一 UTC，供无时区 DATETIME 序列化。
        hide_parameters=True,
        connect_args={"init_command": "SET time_zone = '+00:00'"},
    )
    # 提交后保留已加载属性，避免服务返回 ORM 对象时序列化又触发异步隐式查询。
    # expire_on_commit=False 不承诺长期新鲜；请求间靠新会话和重新查询读取当前账号。
    return engine, async_sessionmaker(engine, expire_on_commit=False)


# FastAPI 在 yield 处借出会话，退出依赖后上下文关闭并归还连接；未完成事务随关闭清理。
# 事务的 begin/提交/回滚由服务或鉴权依赖决定，这里不替调用者自动 commit。
async def get_session(request: Request) -> AsyncIterator[AsyncSession]:
    # 会话只覆盖一次请求，避免上一请求的身份缓存使禁用/降权延后生效。
    async with request.app.state.session_factory() as session:
        yield session
