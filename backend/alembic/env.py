"""Run explicit synchronous migrations without importing the application."""

import os
from logging.config import fileConfig

from sqlalchemy import create_engine, pool
from sqlalchemy.engine import make_url
from sqlalchemy.exc import ArgumentError, SQLAlchemyError

from alembic import context

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = None


def database_url():
    """Require the synchronous environment URL without exposing its value."""
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
    context.configure(
        url=database_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online():
    """Set session UTC at DBAPI connect time, before Alembic owns transactions."""
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
        engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
