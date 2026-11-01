from datetime import datetime

import sqlalchemy as sa
from sqlalchemy.dialects import mysql
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


# ORM 描述 Python 对象与既有 users 表的映射；Alembic 0001 负责实际建表，导入不会建表。
# 方言类型/唯一约束名/默认值须与迁移一致；修改映射本身不会升级已存在的数据库结构。
# Mapped 非 Optional 的列按非空映射；响应字段由 schema 控制，不直接公开 ORM 的所有属性。
class User(Base):
    __tablename__ = "users"
    __table_args__ = (
        sa.UniqueConstraint("username", name="uk_users_username"),
        {
            "mysql_engine": "InnoDB",
            "mysql_charset": "utf8mb4",
            "mysql_collate": "utf8mb4_0900_ai_ci",
        },
    )

    id: Mapped[int] = mapped_column(
        mysql.BIGINT(unsigned=True), primary_key=True, autoincrement=True
    )
    username: Mapped[str] = mapped_column(mysql.VARCHAR(32))
    password_hash: Mapped[str] = mapped_column(mysql.VARCHAR(255))
    # server_default 属于数据库省略列时的默认值；
    # 仓储显式给 role/status，注册不接收客户端角色。
    role: Mapped[str] = mapped_column(mysql.VARCHAR(16), server_default="USER")
    status: Mapped[str] = mapped_column(mysql.VARCHAR(16), server_default="ACTIVE")
    created_at: Mapped[datetime] = mapped_column(
        mysql.DATETIME(fsp=3), server_default=sa.text("CURRENT_TIMESTAMP(3)")
    )
    # MySQL 的 ON UPDATE 必须留在 DDL 默认值文本；server_onupdate 不会生成该子句。
    updated_at: Mapped[datetime] = mapped_column(
        mysql.DATETIME(fsp=3),
        server_default=sa.text("CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3)"),
    )
