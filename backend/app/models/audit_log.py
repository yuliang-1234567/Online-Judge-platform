from datetime import datetime

import sqlalchemy as sa
from sqlalchemy.dialects import mysql
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


# 映射既有迁移中的审计表；导入只登记元数据，不建表或修改数据库。
class AuditLog(Base):
    __tablename__ = "audit_logs"
    __table_args__ = (
        sa.Index("idx_audit_logs_resource", "resource_type", "resource_id", "id"),
        sa.Index("idx_audit_logs_user", "user_id", "id"),
        {
            "mysql_engine": "InnoDB",
            "mysql_charset": "utf8mb4",
            "mysql_collate": "utf8mb4_0900_ai_ci",
        },
    )

    id: Mapped[int] = mapped_column(
        mysql.BIGINT(unsigned=True), primary_key=True, autoincrement=True
    )
    user_id: Mapped[int] = mapped_column(
        mysql.BIGINT(unsigned=True),
        sa.ForeignKey(
            "users.id",
            name="fk_audit_logs_user",
            ondelete="RESTRICT",
            onupdate="RESTRICT",
        ),
    )
    action: Mapped[str] = mapped_column(mysql.VARCHAR(32))
    resource_type: Mapped[str] = mapped_column(mysql.VARCHAR(32))
    resource_id: Mapped[int] = mapped_column(mysql.BIGINT(unsigned=True))
    payload_summary: Mapped[str | None] = mapped_column(mysql.VARCHAR(2048))
    request_id: Mapped[str] = mapped_column(mysql.VARCHAR(64))
    ip: Mapped[str] = mapped_column(mysql.VARCHAR(45))
    created_at: Mapped[datetime] = mapped_column(
        mysql.DATETIME(fsp=3), server_default=sa.text("CURRENT_TIMESTAMP(3)")
    )
