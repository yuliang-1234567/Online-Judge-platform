# 映射既有 test_cases；导入不建表，历史结果的 SET NULL 由既有外键执行。
from datetime import datetime

import sqlalchemy as sa
from sqlalchemy.dialects import mysql
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base
from app.models.problem import OPTIONS


class TestCase(Base):
    __tablename__ = "test_cases"
    __table_args__ = (
        sa.UniqueConstraint("problem_id", "case_index", name="uk_cases_problem_idx"),
        OPTIONS,
    )

    id: Mapped[int] = mapped_column(
        mysql.BIGINT(unsigned=True), primary_key=True, autoincrement=True
    )
    problem_id: Mapped[int] = mapped_column(
        mysql.BIGINT(unsigned=True),
        sa.ForeignKey(
            "problems.id",
            name="fk_cases_problem",
            ondelete="RESTRICT",
            onupdate="RESTRICT",
        ),
    )
    case_index: Mapped[int] = mapped_column(mysql.INTEGER(unsigned=True))
    is_sample: Mapped[bool] = mapped_column(
        mysql.TINYINT(display_width=1), server_default=sa.text("0")
    )
    input_data: Mapped[str] = mapped_column(mysql.MEDIUMTEXT())
    expected_output: Mapped[str] = mapped_column(mysql.MEDIUMTEXT())
    input_size: Mapped[int] = mapped_column(mysql.INTEGER(unsigned=True))
    output_size: Mapped[int] = mapped_column(mysql.INTEGER(unsigned=True))
    sha256: Mapped[str] = mapped_column(mysql.CHAR(64))
    created_at: Mapped[datetime] = mapped_column(
        mysql.DATETIME(fsp=3), server_default=sa.text("CURRENT_TIMESTAMP(3)")
    )
    updated_at: Mapped[datetime] = mapped_column(
        mysql.DATETIME(fsp=3),
        server_default=sa.text("CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3)"),
    )
