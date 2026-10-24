# 由 Alembic 环境调用：upgrade 分三步创建结构，downgrade 反向解除依赖。
# 离线 --sql 只生成语句；真实执行与回退会改变数据库，回退还会删除表内数据。
import sqlalchemy as sa
from sqlalchemy.dialects import mysql

from alembic import op

revision = "0001_initial_schema"
down_revision = None


def upgrade():
    # step 1 建表（按此顺序）：
    # 列声明必须用 mysql 方言类型，不要用 sa.*：
    #   mysql.BIGINT(unsigned=True)     -> BIGINT UNSIGNED
    #   mysql.INTEGER(unsigned=True)    -> INT UNSIGNED
    #   mysql.TINYINT(unsigned=True)    -> TINYINT UNSIGNED
    #   mysql.TINYINT(display_width=1)  -> TINYINT(1)
    #   mysql.DATETIME(fsp=3)           -> DATETIME(3)
    # sa.BigInteger / sa.Integer / sa.SmallInteger / sa.DateTime
    # 会丢 unsigned、显示宽度和精度。
    # users：7 列 / 唯一约束 1 / 外键 无（step 3 添加）
    # tags：3 列 / 唯一约束 1 / 外键 无（step 3 添加）
    # problems：11 列 / 唯一约束 1 / 外键 created_by（step 3 添加）
    # test_cases：11 列 / 唯一约束 1 / 外键 problem_id（step 3 添加）
    # submissions：24 列 / 唯一约束 1 / 外键 user_id、problem_id（step 3 添加）
    # submission_cases：10 列 / 唯一约束 1 /
    #   外键 submission_id、test_case_id（step 3 添加）
    # user_problem_stats：7 列 / 唯一约束 0 /
    #   外键 user_id、problem_id、first_ac_submission_id（step 3 添加）
    # problem_tags：2 列 / 唯一约束 0 / 外键 problem_id、tag_id（step 3 添加）
    # audit_logs：9 列 / 唯一约束 0 / 外键 user_id（step 3 添加）

    # 默认值在数据库端生效：字符串作为字面量，数值和时间函数用 sa.text 表达式。
    # updated_at 的 ON UPDATE 必须随 server_default 写进 DDL；server_onupdate
    # 不生成这段 MySQL DDL。普通外键列引用已有 id，不继承主键的自增含义。
    op.create_table(
        "users",
        sa.Column(
            "id", mysql.BIGINT(unsigned=True), autoincrement=True, nullable=False
        ),
        sa.Column("username", mysql.VARCHAR(32), nullable=False),
        sa.Column("password_hash", mysql.VARCHAR(255), nullable=False),
        sa.Column("role", mysql.VARCHAR(16), server_default="USER", nullable=False),
        sa.Column("status", mysql.VARCHAR(16), server_default="ACTIVE", nullable=False),
        sa.Column(
            "created_at",
            mysql.DATETIME(fsp=3),
            server_default=sa.text("CURRENT_TIMESTAMP(3)"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            mysql.DATETIME(fsp=3),
            server_default=sa.text(
                "CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3)"
            ),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("username", name="uk_users_username"),
        mysql_engine="InnoDB",
        mysql_charset="utf8mb4",
        mysql_collate="utf8mb4_0900_ai_ci",
    )

    op.create_table(
        "tags",
        sa.Column(
            "id", mysql.BIGINT(unsigned=True), autoincrement=True, nullable=False
        ),
        sa.Column("name", mysql.VARCHAR(32), nullable=False),
        sa.Column(
            "created_at",
            mysql.DATETIME(fsp=3),
            server_default=sa.text("CURRENT_TIMESTAMP(3)"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name", name="uk_tags_name"),
        mysql_engine="InnoDB",
        mysql_charset="utf8mb4",
        mysql_collate="utf8mb4_0900_ai_ci",
    )

    op.create_table(
        "problems",
        sa.Column(
            "id", mysql.BIGINT(unsigned=True), autoincrement=True, nullable=False
        ),
        sa.Column("slug", mysql.VARCHAR(64), nullable=False),
        sa.Column("title", mysql.VARCHAR(128), nullable=False),
        sa.Column("description", mysql.MEDIUMTEXT(), nullable=False),
        sa.Column("difficulty", mysql.VARCHAR(8), nullable=False),
        sa.Column(
            "time_limit_ms",
            mysql.INTEGER(unsigned=True),
            server_default=sa.text("1000"),
            nullable=False,
        ),
        sa.Column(
            "memory_limit_mb",
            mysql.INTEGER(unsigned=True),
            server_default=sa.text("256"),
            nullable=False,
        ),
        sa.Column("status", mysql.VARCHAR(16), server_default="DRAFT", nullable=False),
        sa.Column("created_by", mysql.BIGINT(unsigned=True), nullable=False),
        sa.Column(
            "created_at",
            mysql.DATETIME(fsp=3),
            server_default=sa.text("CURRENT_TIMESTAMP(3)"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            mysql.DATETIME(fsp=3),
            server_default=sa.text(
                "CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3)"
            ),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("slug", name="uk_problems_slug"),
        mysql_engine="InnoDB",
        mysql_charset="utf8mb4",
        mysql_collate="utf8mb4_0900_ai_ci",
    )

    op.create_table(
        "test_cases",
        sa.Column(
            "id", mysql.BIGINT(unsigned=True), autoincrement=True, nullable=False
        ),
        sa.Column("problem_id", mysql.BIGINT(unsigned=True), nullable=False),
        sa.Column("case_index", mysql.INTEGER(unsigned=True), nullable=False),
        sa.Column(
            "is_sample",
            mysql.TINYINT(display_width=1),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column("input_data", mysql.MEDIUMTEXT(), nullable=False),
        sa.Column("expected_output", mysql.MEDIUMTEXT(), nullable=False),
        sa.Column("input_size", mysql.INTEGER(unsigned=True), nullable=False),
        sa.Column("output_size", mysql.INTEGER(unsigned=True), nullable=False),
        sa.Column("sha256", mysql.CHAR(64), nullable=False),
        sa.Column(
            "created_at",
            mysql.DATETIME(fsp=3),
            server_default=sa.text("CURRENT_TIMESTAMP(3)"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            mysql.DATETIME(fsp=3),
            server_default=sa.text(
                "CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3)"
            ),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("problem_id", "case_index", name="uk_cases_problem_idx"),
        mysql_engine="InnoDB",
        mysql_charset="utf8mb4",
        mysql_collate="utf8mb4_0900_ai_ci",
    )

    op.create_table(
        "submissions",
        sa.Column(
            "id", mysql.BIGINT(unsigned=True), autoincrement=True, nullable=False
        ),
        sa.Column("user_id", mysql.BIGINT(unsigned=True), nullable=False),
        sa.Column("problem_id", mysql.BIGINT(unsigned=True), nullable=False),
        sa.Column("language", mysql.VARCHAR(16), nullable=False),
        sa.Column("code", mysql.TEXT(), nullable=False),
        sa.Column(
            "time_limit_ms_snapshot", mysql.INTEGER(unsigned=True), nullable=False
        ),
        sa.Column(
            "memory_limit_mb_snapshot", mysql.INTEGER(unsigned=True), nullable=False
        ),
        sa.Column("status", mysql.VARCHAR(20), server_default="QUEUED", nullable=False),
        sa.Column("error_code", mysql.VARCHAR(32), nullable=True),
        sa.Column("error_message", mysql.VARCHAR(2048), nullable=True),
        sa.Column(
            "passed_cases",
            mysql.SMALLINT(unsigned=True),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column(
            "total_cases",
            mysql.SMALLINT(unsigned=True),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column("runtime_ms", mysql.INTEGER(unsigned=True), nullable=True),
        sa.Column("memory_kb", mysql.INTEGER(unsigned=True), nullable=True),
        sa.Column(
            "attempts",
            mysql.TINYINT(unsigned=True),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column(
            "enqueue_count",
            mysql.TINYINT(unsigned=True),
            server_default=sa.text("1"),
            nullable=False,
        ),
        sa.Column("worker_id", mysql.VARCHAR(64), nullable=True),
        sa.Column("lease_expires_at", mysql.DATETIME(fsp=3), nullable=True),
        sa.Column("request_id", mysql.VARCHAR(64), nullable=False),
        sa.Column("idempotency_key", mysql.VARCHAR(64), nullable=False),
        # 入队时间由写入方明确提供；加默认值会掩盖漏传，且混淆入队与建行时间。
        sa.Column("queued_at", mysql.DATETIME(fsp=3), nullable=False),
        sa.Column("started_at", mysql.DATETIME(fsp=3), nullable=True),
        sa.Column("finished_at", mysql.DATETIME(fsp=3), nullable=True),
        sa.Column(
            "created_at",
            mysql.DATETIME(fsp=3),
            server_default=sa.text("CURRENT_TIMESTAMP(3)"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "user_id", "idempotency_key", name="uk_sub_user_idempotency"
        ),
        mysql_engine="InnoDB",
        mysql_charset="utf8mb4",
        mysql_collate="utf8mb4_0900_ai_ci",
    )

    op.create_table(
        "submission_cases",
        sa.Column(
            "id", mysql.BIGINT(unsigned=True), autoincrement=True, nullable=False
        ),
        sa.Column("submission_id", mysql.BIGINT(unsigned=True), nullable=False),
        # 测试点删除后保留判题明细，通过可空引用配合 step 3 的 SET NULL。
        sa.Column("test_case_id", mysql.BIGINT(unsigned=True), nullable=True),
        sa.Column("case_index", mysql.INTEGER(unsigned=True), nullable=False),
        # 这是本次判题的快照，由写入方提供；不能照搬 test_cases.is_sample 的默认 0。
        sa.Column("is_sample", mysql.TINYINT(display_width=1), nullable=False),
        sa.Column("status", mysql.VARCHAR(20), nullable=False),
        sa.Column("runtime_ms", mysql.INTEGER(unsigned=True), nullable=True),
        sa.Column("memory_kb", mysql.INTEGER(unsigned=True), nullable=True),
        sa.Column("stdout_snippet", mysql.VARCHAR(1024), nullable=True),
        sa.Column("stderr_snippet", mysql.VARCHAR(2048), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("submission_id", "case_index", name="uk_sc_sub_idx"),
        mysql_engine="InnoDB",
        mysql_charset="utf8mb4",
        mysql_collate="utf8mb4_0900_ai_ci",
    )

    # 这张表和 problem_tags 用有序联合主键标识关系，两列均为已有 id，禁止自增。
    op.create_table(
        "user_problem_stats",
        sa.Column(
            "user_id", mysql.BIGINT(unsigned=True), autoincrement=False, nullable=False
        ),
        sa.Column(
            "problem_id",
            mysql.BIGINT(unsigned=True),
            autoincrement=False,
            nullable=False,
        ),
        sa.Column(
            "attempts",
            mysql.INTEGER(unsigned=True),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column(
            "solved",
            mysql.TINYINT(display_width=1),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column("first_ac_at", mysql.DATETIME(fsp=3), nullable=True),
        sa.Column("first_ac_submission_id", mysql.BIGINT(unsigned=True), nullable=True),
        sa.Column(
            "updated_at",
            mysql.DATETIME(fsp=3),
            server_default=sa.text(
                "CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3)"
            ),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("user_id", "problem_id"),
        mysql_engine="InnoDB",
        mysql_charset="utf8mb4",
        mysql_collate="utf8mb4_0900_ai_ci",
    )

    op.create_table(
        "problem_tags",
        sa.Column(
            "problem_id",
            mysql.BIGINT(unsigned=True),
            autoincrement=False,
            nullable=False,
        ),
        sa.Column(
            "tag_id", mysql.BIGINT(unsigned=True), autoincrement=False, nullable=False
        ),
        sa.PrimaryKeyConstraint("problem_id", "tag_id"),
        mysql_engine="InnoDB",
        mysql_charset="utf8mb4",
        mysql_collate="utf8mb4_0900_ai_ci",
    )

    op.create_table(
        "audit_logs",
        sa.Column(
            "id", mysql.BIGINT(unsigned=True), autoincrement=True, nullable=False
        ),
        sa.Column("user_id", mysql.BIGINT(unsigned=True), nullable=False),
        sa.Column("action", mysql.VARCHAR(32), nullable=False),
        sa.Column("resource_type", mysql.VARCHAR(32), nullable=False),
        sa.Column("resource_id", mysql.BIGINT(unsigned=True), nullable=False),
        sa.Column("payload_summary", mysql.VARCHAR(2048), nullable=True),
        sa.Column("request_id", mysql.VARCHAR(64), nullable=False),
        sa.Column("ip", mysql.VARCHAR(45), nullable=False),
        sa.Column(
            "created_at",
            mysql.DATETIME(fsp=3),
            server_default=sa.text("CURRENT_TIMESTAMP(3)"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        mysql_engine="InnoDB",
        mysql_charset="utf8mb4",
        mysql_collate="utf8mb4_0900_ai_ci",
    )

    # step 2 建普通索引：10 个
    # problems: idx_problems_status_difficulty_id
    # submissions: idx_sub_user_id, idx_sub_user_problem_id
    #              idx_sub_user_status, idx_sub_status_queued
    #              idx_sub_status_lease, idx_sub_problem_status
    # problem_tags: idx_problem_tags_tag
    # audit_logs: idx_audit_logs_resource, idx_audit_logs_user

    # 先建服务查询的索引，再加外键，使 MySQL 可复用已有索引的最左列前缀；
    # 未覆盖的外键支撑索引由 MySQL 补齐，不在这里重复手建。
    op.create_index(
        "idx_problems_status_difficulty_id",
        "problems",
        ["status", "difficulty", "id"],
        unique=False,
    )

    op.create_index(
        "idx_sub_user_id",
        "submissions",
        ["user_id", "id"],
        unique=False,
    )

    op.create_index(
        "idx_sub_user_problem_id",
        "submissions",
        ["user_id", "problem_id", "id"],
        unique=False,
    )

    op.create_index(
        "idx_sub_user_status",
        "submissions",
        ["user_id", "status"],
        unique=False,
    )

    op.create_index(
        "idx_sub_status_queued",
        "submissions",
        ["status", "queued_at"],
        unique=False,
    )

    op.create_index(
        "idx_sub_status_lease",
        "submissions",
        ["status", "lease_expires_at"],
        unique=False,
    )

    op.create_index(
        "idx_sub_problem_status",
        "submissions",
        ["problem_id", "status"],
        unique=False,
    )

    op.create_index(
        "idx_problem_tags_tag",
        "problem_tags",
        ["tag_id"],
        unique=False,
    )

    op.create_index(
        "idx_audit_logs_resource",
        "audit_logs",
        ["resource_type", "resource_id", "id"],
        unique=False,
    )

    op.create_index(
        "idx_audit_logs_user",
        "audit_logs",
        ["user_id", "id"],
        unique=False,
    )

    # step 3 加外键：12 条
    # problems: fk_problems_creator
    # test_cases: fk_cases_problem
    # submissions: fk_sub_user, fk_sub_problem
    # submission_cases: fk_sc_sub, fk_sc_case
    # user_problem_stats: fk_ups_user, fk_ups_problem
    #                     fk_ups_first_ac_submission
    # problem_tags: fk_problem_tags_problem, fk_problem_tags_tag
    # audit_logs: fk_audit_logs_user

    # 所有目标表已存在才添加外键；设计 DDL 的内联约束在此改为后置 ALTER。
    # 两种呈现的最终结构应一致，删除动作仍逐条显式声明，不靠默认值。
    op.create_foreign_key(
        "fk_problems_creator",
        "problems",
        "users",
        ["created_by"],
        ["id"],
        ondelete="RESTRICT",
        onupdate="RESTRICT",
    )

    op.create_foreign_key(
        "fk_cases_problem",
        "test_cases",
        "problems",
        ["problem_id"],
        ["id"],
        ondelete="RESTRICT",
        onupdate="RESTRICT",
    )

    op.create_foreign_key(
        "fk_sub_user",
        "submissions",
        "users",
        ["user_id"],
        ["id"],
        ondelete="RESTRICT",
        onupdate="RESTRICT",
    )

    op.create_foreign_key(
        "fk_sub_problem",
        "submissions",
        "problems",
        ["problem_id"],
        ["id"],
        ondelete="RESTRICT",
        onupdate="RESTRICT",
    )

    # 明细随所属提交删除；测试点删除则只断开引用，保留历史判题结果。
    op.create_foreign_key(
        "fk_sc_sub",
        "submission_cases",
        "submissions",
        ["submission_id"],
        ["id"],
        ondelete="CASCADE",
        onupdate="RESTRICT",
    )

    op.create_foreign_key(
        "fk_sc_case",
        "submission_cases",
        "test_cases",
        ["test_case_id"],
        ["id"],
        ondelete="SET NULL",
        onupdate="RESTRICT",
    )

    op.create_foreign_key(
        "fk_ups_user",
        "user_problem_stats",
        "users",
        ["user_id"],
        ["id"],
        ondelete="RESTRICT",
        onupdate="RESTRICT",
    )

    op.create_foreign_key(
        "fk_ups_problem",
        "user_problem_stats",
        "problems",
        ["problem_id"],
        ["id"],
        ondelete="RESTRICT",
        onupdate="RESTRICT",
    )

    op.create_foreign_key(
        "fk_ups_first_ac_submission",
        "user_problem_stats",
        "submissions",
        ["first_ac_submission_id"],
        ["id"],
        ondelete="RESTRICT",
        onupdate="RESTRICT",
    )

    op.create_foreign_key(
        "fk_problem_tags_problem",
        "problem_tags",
        "problems",
        ["problem_id"],
        ["id"],
        ondelete="RESTRICT",
        onupdate="RESTRICT",
    )

    op.create_foreign_key(
        "fk_problem_tags_tag",
        "problem_tags",
        "tags",
        ["tag_id"],
        ["id"],
        ondelete="RESTRICT",
        onupdate="RESTRICT",
    )

    op.create_foreign_key(
        "fk_audit_logs_user",
        "audit_logs",
        "users",
        ["user_id"],
        ["id"],
        ondelete="RESTRICT",
        onupdate="RESTRICT",
    )
    pass


def downgrade():
    # step 3 移除外键：12 条（按添加顺序的逆序）
    # audit_logs: fk_audit_logs_user
    # problem_tags: fk_problem_tags_tag, fk_problem_tags_problem
    # user_problem_stats: fk_ups_first_ac_submission, fk_ups_problem
    #                     fk_ups_user
    # submission_cases: fk_sc_case, fk_sc_sub
    # submissions: fk_sub_problem, fk_sub_user
    # test_cases: fk_cases_problem
    # problems: fk_problems_creator

    # 先解除外键，再删可能被外键依赖的索引；否则 MySQL 可拒绝删除索引。
    op.drop_constraint("fk_audit_logs_user", "audit_logs", type_="foreignkey")
    op.drop_constraint("fk_problem_tags_tag", "problem_tags", type_="foreignkey")
    op.drop_constraint("fk_problem_tags_problem", "problem_tags", type_="foreignkey")
    op.drop_constraint(
        "fk_ups_first_ac_submission", "user_problem_stats", type_="foreignkey"
    )
    op.drop_constraint("fk_ups_problem", "user_problem_stats", type_="foreignkey")
    op.drop_constraint("fk_ups_user", "user_problem_stats", type_="foreignkey")
    op.drop_constraint("fk_sc_case", "submission_cases", type_="foreignkey")
    op.drop_constraint("fk_sc_sub", "submission_cases", type_="foreignkey")
    op.drop_constraint("fk_sub_problem", "submissions", type_="foreignkey")
    op.drop_constraint("fk_sub_user", "submissions", type_="foreignkey")
    op.drop_constraint("fk_cases_problem", "test_cases", type_="foreignkey")
    op.drop_constraint("fk_problems_creator", "problems", type_="foreignkey")

    # step 2 移除普通索引：10 个（按创建顺序的逆序）
    # audit_logs: idx_audit_logs_user, idx_audit_logs_resource
    # problem_tags: idx_problem_tags_tag
    # submissions: idx_sub_problem_status, idx_sub_status_lease
    #              idx_sub_status_queued, idx_sub_user_status
    #              idx_sub_user_problem_id, idx_sub_user_id
    # problems: idx_problems_status_difficulty_id

    op.drop_index("idx_audit_logs_user", table_name="audit_logs")
    op.drop_index("idx_audit_logs_resource", table_name="audit_logs")
    op.drop_index("idx_problem_tags_tag", table_name="problem_tags")
    op.drop_index("idx_sub_problem_status", table_name="submissions")
    op.drop_index("idx_sub_status_lease", table_name="submissions")
    op.drop_index("idx_sub_status_queued", table_name="submissions")
    op.drop_index("idx_sub_user_status", table_name="submissions")
    op.drop_index("idx_sub_user_problem_id", table_name="submissions")
    op.drop_index("idx_sub_user_id", table_name="submissions")
    op.drop_index("idx_problems_status_difficulty_id", table_name="problems")

    # step 1 逆序删表：
    # audit_logs, problem_tags, user_problem_stats
    # submission_cases, submissions, test_cases
    # problems, tags, users

    # 最后按建表的逆序删表；这只回退结构，不是恢复已删除业务数据的备份方案。
    op.drop_table("audit_logs")
    op.drop_table("problem_tags")
    op.drop_table("user_problem_stats")
    op.drop_table("submission_cases")
    op.drop_table("submissions")
    op.drop_table("test_cases")
    op.drop_table("problems")
    op.drop_table("tags")
    op.drop_table("users")
    pass
