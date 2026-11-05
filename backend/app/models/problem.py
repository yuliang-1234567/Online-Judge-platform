# 只映射首版迁移已有的三张表；导入不会建表，结构变更仍须经过 Alembic。
from datetime import datetime

import sqlalchemy as sa
from sqlalchemy.dialects import mysql
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base

OPTIONS = {
    "mysql_engine": "InnoDB",
    "mysql_charset": "utf8mb4",
    "mysql_collate": "utf8mb4_0900_ai_ci",
}


class Problem(Base):
    __tablename__ = "problems"
    __table_args__ = (
        sa.UniqueConstraint("slug", name="uk_problems_slug"),
        sa.Index("idx_problems_status_difficulty_id", "status", "difficulty", "id"),
        OPTIONS,
    )

    id: Mapped[int] = mapped_column(
        mysql.BIGINT(unsigned=True), primary_key=True, autoincrement=True
    )
    slug: Mapped[str] = mapped_column(mysql.VARCHAR(64))
    title: Mapped[str] = mapped_column(mysql.VARCHAR(128))
    description: Mapped[str] = mapped_column(mysql.MEDIUMTEXT())
    difficulty: Mapped[str] = mapped_column(mysql.VARCHAR(8))
    time_limit_ms: Mapped[int] = mapped_column(
        mysql.INTEGER(unsigned=True), server_default=sa.text("1000")
    )
    memory_limit_mb: Mapped[int] = mapped_column(
        mysql.INTEGER(unsigned=True), server_default=sa.text("256")
    )
    status: Mapped[str] = mapped_column(mysql.VARCHAR(16), server_default="DRAFT")
    created_by: Mapped[int] = mapped_column(
        mysql.BIGINT(unsigned=True),
        sa.ForeignKey(
            "users.id",
            name="fk_problems_creator",
            ondelete="RESTRICT",
            onupdate="RESTRICT",
        ),
    )
    created_at: Mapped[datetime] = mapped_column(
        mysql.DATETIME(fsp=3), server_default=sa.text("CURRENT_TIMESTAMP(3)")
    )
    updated_at: Mapped[datetime] = mapped_column(
        mysql.DATETIME(fsp=3),
        server_default=sa.text("CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3)"),
    )


class Tag(Base):
    __tablename__ = "tags"
    __table_args__ = (sa.UniqueConstraint("name", name="uk_tags_name"), OPTIONS)

    id: Mapped[int] = mapped_column(
        mysql.BIGINT(unsigned=True), primary_key=True, autoincrement=True
    )
    name: Mapped[str] = mapped_column(mysql.VARCHAR(32))
    created_at: Mapped[datetime] = mapped_column(
        mysql.DATETIME(fsp=3), server_default=sa.text("CURRENT_TIMESTAMP(3)")
    )


class ProblemTag(Base):
    __tablename__ = "problem_tags"
    __table_args__ = (sa.Index("idx_problem_tags_tag", "tag_id"), OPTIONS)

    problem_id: Mapped[int] = mapped_column(
        mysql.BIGINT(unsigned=True),
        sa.ForeignKey(
            "problems.id",
            name="fk_problem_tags_problem",
            ondelete="RESTRICT",
            onupdate="RESTRICT",
        ),
        primary_key=True,
        autoincrement=False,
    )
    tag_id: Mapped[int] = mapped_column(
        mysql.BIGINT(unsigned=True),
        sa.ForeignKey(
            "tags.id",
            name="fk_problem_tags_tag",
            ondelete="RESTRICT",
            onupdate="RESTRICT",
        ),
        primary_key=True,
        autoincrement=False,
    )
