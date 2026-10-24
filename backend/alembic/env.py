"""Run explicit synchronous migrations without importing the application."""

# Alembic 命令加载此入口，再调版本文件的 upgrade/downgrade；应用启动不经过这里。
import os
from logging.config import fileConfig

from sqlalchemy import create_engine, pool
from sqlalchemy.engine import make_url
from sqlalchemy.exc import ArgumentError, SQLAlchemyError

from alembic import context

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# 不导入应用模型作为自动比对目标；当前迁移正文是显式审核的版本声明。
target_metadata = None


def database_url():
    """Require the synchronous environment URL without exposing its value."""
    # URL 只在进程内解析，错误不回显原值，避免把账号密码带进日志。
    value = os.environ.get("DATABASE_URL_SYNC", "").strip()
    if not value:
        raise RuntimeError("DATABASE_URL_SYNC 缺失或为空")
    try:
        url = make_url(value)
    except (ArgumentError, ValueError):
        raise RuntimeError("DATABASE_URL_SYNC 格式无效") from None
    if url.drivername != "mysql+pymysql":
        raise RuntimeError("DATABASE_URL_SYNC 必须使用 mysql+pymysql 驱动")
    return url


def run_migrations_offline():
    """Render SQL only when the operator explicitly requests offline mode."""
    # --sql 仍需 URL 选定 MySQL 方言，但不创建 Engine；参数以字面量写进输出 SQL。
    context.configure(
        url=database_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    # 离线事务上下文用于组织生成的 SQL，不代表 MySQL 已解析或执行这些语句。
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online():
    """Set session UTC at DBAPI connect time, before Alembic owns transactions."""
    # 在线模式才连接数据库；NullPool 不保留连接，连接建立时先设 UTC，
    # 避免临时执行 SET 抢先开启事务，干扰 Alembic 管理的迁移事务。
    engine = create_engine(
        database_url(),
        poolclass=pool.NullPool,
        connect_args={
            "init_command": "SET time_zone = '+00:00'",
            "connect_timeout": 5,
        },
        echo=False,
        hide_parameters=True,
    )
    try:
        with engine.connect() as connection:
            context.configure(
                connection=connection,
                target_metadata=target_metadata,
            )
            with context.begin_transaction():
                context.run_migrations()
    except SQLAlchemyError:
        raise RuntimeError(
            "迁移数据库连接或执行失败；请检查连接配置、服务状态及迁移正文"
        ) from None
    finally:
        # 无论迁移成功还是抛错，都由创建 Engine 的这一层释放其资源。
        engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
