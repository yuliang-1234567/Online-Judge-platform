"""认证与 M1 受控入口：按 suite 隔离验证、留证及按归属清理。"""

# /tmp/oj-auth-check-<uid>.lock 跨 checkout 共享，串行保护固定的 oj_auth_check 库。

import argparse
import base64
import binascii
import fcntl
import ipaddress
import json
import os
import re
import signal
import stat
import subprocess
import sys
import time
import unicodedata
import uuid
from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from dotenv import dotenv_values
from pydantic import SecretStr
from sqlalchemy.engine import make_url
from sqlalchemy.exc import ArgumentError

ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "backend"
# 文件路径启动时 Python 只加入 tools/；固定加入 backend，保持与 -m 一致。
if __package__ in (None, ""):
    sys.path.insert(0, str(BACKEND))
DATABASE = "oj_auth_check"
ACCOUNT_HOST = "127.0.0.1"
PREFIX_ROOT = "oj:ratelimit:auth-check:"
ACCOUNT_NAME_PATTERN = re.compile(r"oac_[am]_[a-z2-7]{26}")
LOCK_PATH = Path("/tmp") / f"oj-auth-check-{os.getuid()}.lock"
CHILD_ENV_KEYS = frozenset(
    {
        "AUTH_INTEGRATION_DATABASE_URL",
        "AUTH_INTEGRATION_REDIS_URL",
        "JWT_SECRET",
        "RATE_LIMIT_KEY_PREFIX",
    }
)

# 固定用例与表授权，拒绝任意路径/表名进入 argv 或 SQL。
SUITE_FILES = {
    "auth": "tests/integration/test_auth.py",
    "m1-access": "tests/integration/test_admin_and_audit.py",
    "m1-problems": "tests/integration/test_problem_lifecycle.py",
}
APPLICATION_DML = "SELECT, INSERT, UPDATE, DELETE"
SUITE_TABLES = {
    "auth": {"users": APPLICATION_DML},
    "m1-access": {"users": APPLICATION_DML, "audit_logs": "SELECT, INSERT"},
    "m1-problems": {
        "users": APPLICATION_DML,
        "audit_logs": "SELECT, INSERT",
        "problems": APPLICATION_DML,
        "tags": APPLICATION_DML,
        "problem_tags": APPLICATION_DML,
        "test_cases": APPLICATION_DML,
        "submissions": "SELECT, INSERT, UPDATE",
        "submission_cases": "SELECT, INSERT",
    },
}


class RunnerError(Exception):
    # message 只能由本模块提供固定文案，不能传入带凭据的底层异常正文。
    def __init__(
        self, message: str, exit_code: int = 70, driver_code: int | None = None
    ):
        super().__init__(message)
        self.exit_code = exit_code
        self.driver_code = driver_code
        self.reported = False


def suite_test_file(suite: str) -> str:
    if suite not in SUITE_FILES:
        raise RunnerError("验证范围无效；原值不回显", 64)
    return SUITE_FILES[suite]


def evidence_directory(state: "RunState") -> Path:
    suite_test_file(state.suite)
    base = ROOT / "local-reference/runtime"
    if state.suite == "auth":
        return base / "07.5b" / state.run_id
    return base / "m1" / state.suite / state.run_id


class SqlExecutor(Protocol):
    """管理语句的注入边界；离线用记录器，实库用受控 PyMySQL 执行器。"""

    def execute(self, sql: str, params: tuple[object, ...] = ()) -> None: ...

    def query(
        self, sql: str, params: tuple[object, ...] = ()
    ) -> Sequence[tuple[object, ...]]: ...


CREATE_DATABASE_SQL = (
    "CREATE DATABASE `oj_auth_check` CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci"
)
CREATE_OWNER_TABLE_SQL = """CREATE TABLE `oj_auth_check`.`__auth_check_owner` (
    singleton TINYINT UNSIGNED NOT NULL PRIMARY KEY,
    run_id CHAR(32) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    app_user VARCHAR(32) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    migration_user VARCHAR(32) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    created_at DATETIME(3) NOT NULL,
    CONSTRAINT ck_auth_check_owner_singleton CHECK (singleton = 1)
) ENGINE=InnoDB"""
INSERT_OWNER_SQL = (
    "INSERT INTO `oj_auth_check`.`__auth_check_owner` "
    "(singleton, run_id, app_user, migration_user, created_at) "
    "VALUES (1, %s, %s, %s, UTC_TIMESTAMP(3))"
)
READ_OWNER_SQL = (
    "SELECT singleton, run_id, app_user, migration_user "
    "FROM `oj_auth_check`.`__auth_check_owner`"
)
DEV_TABLE_COUNT_SQL = (
    "SELECT COUNT(*) FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_SCHEMA = %s"
)
DEV_VERSION_EXISTS_SQL = (
    "SELECT COUNT(*) FROM INFORMATION_SCHEMA.TABLES "
    "WHERE TABLE_SCHEMA = %s AND TABLE_NAME = %s"
)
DEV_VERSION_SQL = "SELECT version_num FROM `oj`.`alembic_version`"


@dataclass(frozen=True)
class DevelopmentSnapshot:
    table_count: int
    # None 表示版本表不存在；空元组表示表存在但无版本行，不能混称“未迁移”。
    versions: tuple[str, ...] | None


def development_snapshot_values(snapshot: DevelopmentSnapshot) -> dict:
    # null 是版本表不存在，[] 是存在但无版本行；多版本记录完整保留。
    return {
        "table_count": snapshot.table_count,
        "alembic_version": (
            list(snapshot.versions) if snapshot.versions is not None else None
        ),
    }


def _require_isolated_database(database: str) -> None:
    if database != DATABASE:
        raise RunnerError("管理动作只允许固定隔离库", 64)


def _execute(executor: SqlExecutor, sql: str, params: tuple[object, ...] = ()) -> None:
    try:
        executor.execute(sql, params)
    except RunnerError:
        raise
    except Exception as error:
        raise RunnerError(
            f"管理执行失败（{type(error).__name__}）；异常正文已隐藏"
        ) from None


def _query(
    executor: SqlExecutor, sql: str, params: tuple[object, ...] = ()
) -> Sequence[tuple[object, ...]]:
    try:
        return executor.query(sql, params)
    except RunnerError:
        raise
    except Exception as error:
        raise RunnerError(
            f"管理查询失败（{type(error).__name__}）；异常正文已隐藏"
        ) from None


def create_isolated_database(executor: SqlExecutor, database: str = DATABASE) -> None:
    # 不用 IF NOT EXISTS：旧库不能被解释成当前创建成功，后续也不得按库名接管。
    _require_isolated_database(database)
    _execute(executor, CREATE_DATABASE_SQL)


def create_owner_table(executor: SqlExecutor, database: str = DATABASE) -> None:
    _require_isolated_database(database)
    _execute(executor, CREATE_OWNER_TABLE_SQL)


def _snapshot_count(rows: Sequence[tuple[object, ...]]) -> int:
    if (
        len(rows) != 1
        or len(rows[0]) != 1
        or type(rows[0][0]) is not int
        or rows[0][0] < 0
    ):
        raise RunnerError("开发库快照计数格式无效", 65)
    return rows[0][0]


def read_development_snapshot(executor: SqlExecutor) -> DevelopmentSnapshot:
    """只生成并交付 SELECT；不创建缺失的版本表，也不修改开发库。"""
    count = _snapshot_count(_query(executor, DEV_TABLE_COUNT_SQL, ("oj",)))
    exists = _snapshot_count(
        _query(executor, DEV_VERSION_EXISTS_SQL, ("oj", "alembic_version"))
    )
    if exists not in (0, 1):
        raise RunnerError("开发库版本表计数无效", 65)
    if not exists:
        return DevelopmentSnapshot(count, None)
    rows = _query(executor, DEV_VERSION_SQL)
    if any(len(row) != 1 or not isinstance(row[0], str) or not row[0] for row in rows):
        raise RunnerError("开发库版本记录格式无效", 65)
    return DevelopmentSnapshot(count, tuple(sorted(row[0] for row in rows)))


@dataclass(frozen=True)
class OwnerRecord:
    run_id: str
    app_user: str
    migration_user: str


def write_owner(
    executor: SqlExecutor, run_id: str, database: str = DATABASE
) -> OwnerRecord:
    _require_isolated_database(database)
    app_user, migration_user = account_names(run_id)
    _execute(executor, INSERT_OWNER_SQL, (run_id, app_user, migration_user))
    return OwnerRecord(run_id, app_user, migration_user)


def read_owner(
    executor: SqlExecutor, run_id: str, database: str = DATABASE
) -> OwnerRecord:
    _require_isolated_database(database)
    app_user, migration_user = account_names(run_id)
    rows = _query(executor, READ_OWNER_SQL)
    if (
        len(rows) != 1
        or len(rows[0]) != 4
        or type(rows[0][0]) is not int
        or tuple(rows[0]) != (1, run_id, app_user, migration_user)
    ):
        raise RunnerError("服务端 owner 缺失或与本轮不符", 65)
    return OwnerRecord(rows[0][1], rows[0][2], rows[0][3])


def cleanup_account_names(owner: OwnerRecord, run_id: str) -> tuple[str, str]:
    """只派生清理候选名，不执行删除；输入必须来自服务端 owner 的读取结果。"""
    _run_uuid(run_id)
    if owner.run_id != run_id:
        raise RunnerError("owner 不属于本轮，拒绝派生清理账号", 65)
    # 清理候选一律由 owner 行 run_id 重新派生，已存账号字符串仅用于比对。
    names = account_names(owner.run_id)
    if (owner.app_user, owner.migration_user) != names:
        raise RunnerError("owner 账号与完整 run_id 不符", 65)
    return names


def sql_literal(value: str) -> str:
    """MySQL 单引号字面量；调用会话必须未启用 NO_BACKSLASH_ESCAPES。"""
    if not isinstance(value, str) or any(
        unicodedata.category(char) in {"Cc", "Cf", "Cs"} for char in value
    ):
        raise RunnerError("SQL 字面量包含无效类型或控制字符；原值不回显", 64)
    return "'" + value.replace("\\", "\\\\").replace("'", "''") + "'"


def validate_account_host(host: str) -> str:
    # 只接受服务端观察到的精确 IPv4；不接受通配符、主机名或自动 DNS 猜测。
    try:
        if not isinstance(host, str) or str(ipaddress.IPv4Address(host)) != host:
            raise ValueError
    except (ValueError, ipaddress.AddressValueError):
        raise RunnerError("账号 host 必须为已核实的精确 IPv4", 64) from None
    return host


def account_literal(run_id: str, role: str, host: str = ACCOUNT_HOST) -> str:
    name = validate_account_name(account_name(run_id, role), run_id, role)
    validate_account_host(host)
    return f"{sql_literal(name)}@{sql_literal(host)}"


def _password_value(password: SecretStr) -> str:
    if not isinstance(password, SecretStr):
        raise RunnerError("测试账号密码必须使用 SecretStr", 64)
    raw = password.get_secret_value()
    if not isinstance(raw, str) or not raw or "\0" in raw:
        raise RunnerError("测试账号密码无效；原值不回显", 64)
    return raw


def create_test_accounts(
    executor: SqlExecutor,
    run_id: str,
    app_password: SecretStr,
    migration_password: SecretStr,
    database: str = DATABASE,
    *,
    host: str = ACCOUNT_HOST,
) -> None:
    _require_isolated_database(database)
    passwords = (_password_value(app_password), _password_value(migration_password))
    statements = []
    # 所有字段先渲染/校验完再执行，第二个参数错误不能留下第一个账号。
    for code, password, role in zip(
        ("a", "m"), passwords, ("application", "migration"), strict=True
    ):
        attributes = json.dumps(
            {"oj_auth_check_run_id": run_id, "role": role}, sort_keys=True
        )
        statements.append(
            f"CREATE USER {account_literal(run_id, code, host)} "
            f"IDENTIFIED WITH caching_sha2_password BY {sql_literal(password)} "
            f"ATTRIBUTE {sql_literal(attributes)}"
        )
    for sql in statements:
        _execute(executor, sql)


def grant_migration_account(
    executor: SqlExecutor,
    run_id: str,
    database: str = DATABASE,
    *,
    host: str = ACCOUNT_HOST,
) -> None:
    _require_isolated_database(database)
    _execute(
        executor,
        "GRANT CREATE, ALTER, DROP, INDEX, REFERENCES, SELECT, INSERT, UPDATE, DELETE "
        f"ON `oj_auth_check`.* TO {account_literal(run_id, 'm', host)}",
    )


def grant_application_account(
    executor: SqlExecutor,
    run_id: str,
    database: str = DATABASE,
    *,
    host: str = ACCOUNT_HOST,
    suite: str = "auth",
) -> None:
    # 迁移后按 suite 授权；审计只读/追加，应用不能改 owner 或执行 DDL。
    _require_isolated_database(database)
    suite_test_file(suite)
    account = account_literal(run_id, "a", host)
    # 造在途数据需应用会话插入，仅 m1-problems 放宽，auth suite 不变。
    # 提交记录只需插入/改状态，历史明细只需插入；均不授 DELETE，明细也不授 UPDATE。
    for table_name, privileges in SUITE_TABLES[suite].items():
        _execute(
            executor,
            f"GRANT {privileges} ON `oj_auth_check`.`{table_name}` TO {account}",
        )
    _execute(
        executor,
        f"GRANT SELECT ON `oj_auth_check`.`__auth_check_owner` TO {account}",
    )


@dataclass(frozen=True)
class ManagementCredentials:
    # SecretStr 防意外 repr 泄露；仍不得序列化、记录或传给子进程。
    mysql_password: SecretStr
    redis_password: SecretStr


@dataclass
class RunState:
    run_id: str
    received_signal: int | None = None
    resources_started: bool = False
    suite: str = "auth"

    def check(self):
        if self.received_signal is not None:
            raise RunnerError("本轮已中断", self.signal_exit_code)

    def receive_signal(self, signum, _frame):
        # 只记首次信号，不能在异步信号处理器里做 I/O 或打断清理。
        if self.received_signal is None:
            self.received_signal = signum

    @property
    def signal_exit_code(self) -> int | None:
        return 128 + self.received_signal if self.received_signal is not None else None


def _run_uuid(run_id: str) -> uuid.UUID:
    if not isinstance(run_id, str) or not re.fullmatch(r"[0-9a-f]{32}", run_id):
        raise RunnerError("run_id 必须为 uuid4().hex", 64)
    value = uuid.UUID(run_id)
    if value.version != 4:
        raise RunnerError("run_id 必须为 uuid4().hex", 64)
    return value


def rate_limit_prefix(run_id: str) -> str:
    return PREFIX_ROOT + _run_uuid(run_id).hex


def account_name(run_id: str, role: str) -> str:
    """完整 UUID 可逆编码为 26 字符，加角色前缀后恰好 32 字符；不截断 UUID。"""
    value = _run_uuid(run_id)
    if role not in ("a", "m"):
        raise RunnerError("账号角色必须为 a 或 m", 64)
    encoded = base64.b32encode(value.bytes).decode("ascii").rstrip("=").lower()
    name = f"oac_{role}_{encoded}"
    # 显式检查即使 python -O 也生效；模板保留下划线，完整账号正好 32 字符。
    if (
        re.fullmatch(r"[a-z2-7]{26}", encoded) is None
        or len(name) != 32
        or ACCOUNT_NAME_PATTERN.fullmatch(name) is None
    ):
        raise RunnerError("账号编码长度或字符集异常")
    return name


def account_names(run_id: str) -> tuple[str, str]:
    return account_name(run_id, "a"), account_name(run_id, "m")


def validate_account_name(name: str, run_id: str, role: str) -> str:
    expected = account_name(run_id, role)
    if (
        not isinstance(name, str)
        or len(name) != 32
        or ACCOUNT_NAME_PATTERN.fullmatch(name) is None
        or not name.startswith(f"oac_{role}_")
    ):
        raise RunnerError("账号名格式或角色无效", 64)
    try:
        decoded = uuid.UUID(bytes=base64.b32decode(name[6:].upper() + "======"))
    except (binascii.Error, ValueError):
        raise RunnerError("账号名编码无效", 64) from None
    # 重编码比较也拒绝末字符 padding bits 的非规范别名，不能只比较解码字节。
    if decoded.hex != run_id or name != expected:
        raise RunnerError("账号名不属于本轮完整 run_id", 64)
    return name


def validate_child_environment(environment: Mapping[str, str]) -> str:
    """只核对格式与目标，不读 .env、不连接；返回值不代表服务端归属成立。"""
    if set(environment) != CHILD_ENV_KEYS:
        raise RunnerError("子进程配置键集必须精确匹配四项白名单", 64)
    prefix = environment.get("RATE_LIMIT_KEY_PREFIX", "")
    run_id = prefix.removeprefix(PREFIX_ROOT)
    if prefix != rate_limit_prefix(run_id):
        raise RunnerError("限流前缀必须精确包含本轮 run_id", 64)
    try:
        database = make_url(environment.get("AUTH_INTEGRATION_DATABASE_URL", ""))
        redis = make_url(environment.get("AUTH_INTEGRATION_REDIS_URL", ""))
        database_ok = (
            database.drivername == "mysql+asyncmy"
            and database.host == "127.0.0.1"
            and database.port == 13306
            and database.database == DATABASE
            and bool(database.password)
            and not database.query
        )
        redis_ok = (
            redis.drivername == "redis"
            and redis.host == "127.0.0.1"
            and redis.port == 16379
            and redis.database == "4"
            and bool(redis.password)
            # 无用户名的 redis://:password@... 会被解析为空字符串。
            and redis.username in (None, "", "default")
            and not redis.query
        )
    except (ArgumentError, ValueError, TypeError):
        raise RunnerError("集成连接配置格式无效；原值不回显", 64) from None
    if not database_ok or not redis_ok:
        raise RunnerError("集成连接必须指向隔离库及 Redis /4", 64)
    validate_account_name(database.username, run_id, "a")
    if len(environment.get("JWT_SECRET", "").encode("utf-8")) < 32:
        raise RunnerError("集成 JWT_SECRET 至少需要 32 字节", 64)
    return run_id


def build_child_environment(
    run_id: str, database_url: str, redis_url: str, jwt_secret: str
) -> dict[str, str]:
    # 从空字典构造四项白名单；不复制 os.environ，也不把 dotenv 字典转交子进程。
    # Python 子进程使用绝对解释器路径及 -B，无需继承 PATH/PYTHONPATH/开发配置。
    environment = {
        "AUTH_INTEGRATION_DATABASE_URL": database_url,
        "AUTH_INTEGRATION_REDIS_URL": redis_url,
        "JWT_SECRET": jwt_secret,
        "RATE_LIMIT_KEY_PREFIX": rate_limit_prefix(run_id),
    }
    if set(environment) != CHILD_ENV_KEYS:
        raise RunnerError("子进程配置键集必须精确匹配四项白名单", 64)
    validate_child_environment(environment)
    return environment


def load_application_settings(environment: Mapping[str, str]):
    """仅供通过服务端归属门禁的 pytest 子进程调用；不在入口父进程映射环境。"""
    run_id = validate_child_environment(environment)
    # 选择 AUTH_INTEGRATION_* 传递协议；显式映射在导入 app 配置模块之前完成。
    # 同步迁移 URL 不属于应用进程，不能顺手映射或继承到 pytest。
    os.environ.pop("DATABASE_URL_SYNC", None)
    os.environ.update(
        DATABASE_URL=environment["AUTH_INTEGRATION_DATABASE_URL"],
        REDIS_URL=environment["AUTH_INTEGRATION_REDIS_URL"],
        JWT_SECRET=environment["JWT_SECRET"],
        RATE_LIMIT_KEY_PREFIX=environment["RATE_LIMIT_KEY_PREFIX"],
    )
    from app.core.config import Settings

    configured = Settings()
    actual = {
        "AUTH_INTEGRATION_DATABASE_URL": configured.database_url.get_secret_value(),
        "AUTH_INTEGRATION_REDIS_URL": configured.redis_url.get_secret_value(),
        "JWT_SECRET": configured.jwt_secret.get_secret_value(),
        "RATE_LIMIT_KEY_PREFIX": configured.rate_limit_key_prefix,
    }
    # 重新核实际 Settings：必须仍为 oj_auth_check、Redis /4 及本轮前缀，不靠默认值。
    if validate_child_environment(actual) != run_id:
        raise RunnerError("应用实际配置不属于本轮 run_id", 64)
    return configured


def build_migration_environment(run_id: str, database_url_sync: str) -> dict[str, str]:
    """同步迁移使用独立 oac_m_ 账号；管理凭据和应用密码均不进入此子环境。"""
    prefix = rate_limit_prefix(run_id)
    try:
        url = make_url(database_url_sync)
        valid = (
            url.drivername == "mysql+pymysql"
            and url.host == "127.0.0.1"
            and url.port == 13306
            and url.database == DATABASE
            and bool(url.password)
            and not url.query
        )
    except (ArgumentError, ValueError, TypeError):
        raise RunnerError("迁移配置格式无效；原值不回显", 64) from None
    if not valid:
        raise RunnerError("迁移必须使用隔离库及本轮迁移账号", 64)
    validate_account_name(url.username, run_id, "m")
    return {
        "AUTH_INTEGRATION_DATABASE_URL_SYNC": database_url_sync,
        "RATE_LIMIT_KEY_PREFIX": prefix,
    }


def map_migration_environment(environment: Mapping[str, str]) -> dict[str, str]:
    # 迁移子进程必须在导入 Alembic 前映射，不能继承开发连接配置。
    run_id = environment.get("RATE_LIMIT_KEY_PREFIX", "").removeprefix(PREFIX_ROOT)
    safe = build_migration_environment(
        run_id, environment.get("AUTH_INTEGRATION_DATABASE_URL_SYNC", "")
    )
    if safe["RATE_LIMIT_KEY_PREFIX"] != environment.get("RATE_LIMIT_KEY_PREFIX"):
        raise RunnerError("迁移前缀不属于本轮 run_id", 64)
    return {"DATABASE_URL_SYNC": safe["AUTH_INTEGRATION_DATABASE_URL_SYNC"]}


def load_management_credentials() -> ManagementCredentials:
    try:
        values = dotenv_values(
            ROOT / "deploy/.env", encoding="utf-8-sig", interpolate=False
        )
        mysql = values.get("MYSQL_ROOT_PASSWORD")
        redis = values.get("REDIS_PASSWORD")
        if not mysql or not redis:
            raise ValueError
        return ManagementCredentials(SecretStr(mysql), SecretStr(redis))
    except (OSError, ValueError):
        raise RunnerError("管理配置缺失或无效；配置值不回显", 64) from None


@contextmanager
def exclusive_lock(path: Path = LOCK_PATH) -> Iterator[None]:
    # 稳定 inode 不在退出时 unlink，防两个进程锁到不同文件；拒绝符号链接和他人文件。
    descriptor = os.open(
        path, os.O_CREAT | os.O_RDWR | os.O_CLOEXEC | os.O_NOFOLLOW, 0o600
    )
    try:
        info = os.fstat(descriptor)
        if (
            not stat.S_ISREG(info.st_mode)
            or info.st_uid != os.getuid()
            or stat.S_IMODE(info.st_mode) != 0o600
        ):
            raise RunnerError("锁文件归属或权限不正确", 64)
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise RunnerError("认证隔离验证入口已被占用", 75) from None
        yield
    finally:
        os.close(descriptor)


@contextmanager
def signal_handlers(state: RunState) -> Iterator[None]:
    previous = {}
    try:
        for signum in (signal.SIGINT, signal.SIGTERM):
            previous[signum] = signal.signal(signum, state.receive_signal)
        yield
    finally:
        for signum, handler in previous.items():
            signal.signal(signum, handler)


class ChildSupervisor:
    """入口独占本轮子进程；停止进程组并确认退出之后才能清理实资源。"""

    def __init__(self, state: RunState):
        self.state = state
        self.child: subprocess.Popen | None = None
        self.test_summary = {}

    def run_pytest(self, environment: dict[str, str]) -> int:
        # 不透传 traceback 或捕获内容，测试可能在断言中包含连接配置。
        self.state.check()
        test_file = suite_test_file(self.state.suite)
        if self.child is not None:
            raise RunnerError("本轮子进程尚未回收")
        if validate_child_environment(environment) != self.state.run_id:
            raise RunnerError("子进程配置不属于本轮 run_id", 64)
        allowed = build_child_environment(
            self.state.run_id,
            environment.get("AUTH_INTEGRATION_DATABASE_URL", ""),
            environment.get("AUTH_INTEGRATION_REDIS_URL", ""),
            environment.get("JWT_SECRET", ""),
        )
        self.child = subprocess.Popen(
            [
                sys.executable,
                "-B",
                "-m",
                "pytest",
                "--auth-integration",
                test_file,
                "-q",
                "--maxfail=1",
                "--tb=no",
                "--show-capture=no",
                "-p",
                "no:cacheprovider",
            ],
            cwd=BACKEND,
            env=allowed,
            start_new_session=True,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
        )
        deadline = time.monotonic() + 180
        while self.state.received_signal is None:
            if time.monotonic() > deadline:
                raise RunnerError("集成测试超时", 70)
            try:
                output, _ = self.child.communicate(timeout=0.1)
                # 只提取数字及静态用例标识；绝不透传断言、日志或 traceback。
                self.test_summary = {
                    kind: int(matches[-1])
                    if (matches := re.findall(r"(\d+) " + kind, output))
                    else 0
                    for kind in ("passed", "failed", "error", "skipped")
                }
                self.test_summary["failed_tests"] = re.findall(
                    r"^FAILED (tests/integration/[A-Za-z0-9_./:]+)", output, re.M
                )
                result = self.child.returncode
                if result == 0 and (
                    not self.test_summary["passed"] or self.test_summary["skipped"]
                ):
                    raise RunnerError("集成未执行有效用例或存在 skip", 70)
                return result if result >= 0 else 128 - result
            except subprocess.TimeoutExpired:
                continue
        return self.state.signal_exit_code

    def stop(self) -> None:
        if self.child is None:
            return  # 尚未启动子进程，不是未实现的资源清理分支。
        group = self.child.pid  # start_new_session=True，使本轮 PID 同时成为进程组 ID。
        try:
            os.killpg(group, self.state.received_signal or signal.SIGTERM)
        except ProcessLookupError:
            pass  # 整个组已退出仍须 wait 回收直接子进程。
        try:
            self.child.wait(timeout=5)
        except subprocess.TimeoutExpired:
            os.killpg(group, signal.SIGKILL)
            self.child.wait(timeout=5)
        # 直接子进程结束不代表其后代已结束；有界等待后仍存在则拒绝资源清理。
        deadline = time.monotonic() + 2
        while True:
            try:
                os.killpg(group, 0)
            except ProcessLookupError:
                self.child = None
                return
            os.killpg(group, signal.SIGKILL)
            if time.monotonic() >= deadline:
                raise RunnerError("本轮进程组仍未退出，拒绝资源清理")
            time.sleep(0.05)


def run_full_flow(
    state: RunState, credentials: ManagementCredentials, supervisor: ChildSupervisor
) -> int:
    # 默认认证八项，显式 suite 选择 M1 用例；错误共用既有收尾路径。
    return first_database_round(state, credentials, supervisor, run_tests=True)


def execute_locked(state: RunState) -> int:
    supervisor = ChildSupervisor(state)
    result = 70
    try:
        result = run_full_flow(state, load_management_credentials(), supervisor)
    except RunnerError as error:
        if not error.reported:
            print(str(error), file=sys.stderr)
        result = error.exit_code
    except Exception as error:
        print(f"入口失败（{type(error).__name__}）；异常正文已隐藏", file=sys.stderr)
    finally:
        try:
            supervisor.stop()
        except Exception:
            print("进程组未确认退出，禁止清理", file=sys.stderr)
            if result == 0:
                result = 70
    return state.signal_exit_code or result


class SafeArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        # argparse 默认会回显未知参数；误把凭据放进 argv 时也不能将其打印。
        self.print_usage(sys.stderr)
        self.exit(2, "参数无效；请使用 --help，参数原值不回显\n")


def main(argv: list[str] | None = None) -> int:
    parser = SafeArgumentParser(
        description=("认证/M1 隔离验证；失败先停止业务并留证，仅清理归属匹配的资源。"),
        allow_abbrev=False,
    )
    # --help / 未知参数在读 .env、生成 run_id、取锁之前处理；无 --clear 或子命令。
    parser.add_argument(
        "--suite",
        choices=tuple(SUITE_FILES),
        default="auth",
        help="默认 auth 保持原八项认证；M1 范围须单独批准实库运行",
    )
    options = parser.parse_args(argv)
    state = RunState(uuid.uuid4().hex, suite=options.suite)
    with signal_handlers(state):
        try:
            with exclusive_lock():
                return execute_locked(state)
        except RunnerError as error:
            print(str(error), file=sys.stderr)
            return state.signal_exit_code or error.exit_code
        except OSError as error:
            print(
                f"入口锁不可用（{type(error).__name__}）；异常正文已隐藏",
                file=sys.stderr,
            )
            return state.signal_exit_code or 70


def driver_error_code(error: BaseException) -> int | None:
    pending, seen = [error], set()
    while pending:
        current = pending.pop()
        if current is None or id(current) in seen:
            continue
        seen.add(id(current))
        args = getattr(current, "args", ())
        if args and type(args[0]) is int:
            return args[0]
        pending.extend(
            getattr(current, attr, None)
            for attr in ("orig", "__cause__", "__context__")
        )
    return None


class PyMySqlExecutor:
    """真实同步执行器；不记录 SQL 正文，错误只保留类别与整数错误码。"""

    def __init__(
        self,
        username: str,
        password: SecretStr,
        database: str | None = None,
        *,
        state: RunState | None = None,
    ):
        import pymysql

        self.state = state
        self.affected_rows = 0
        self.connection = None
        if username != "root" and ACCOUNT_NAME_PATTERN.fullmatch(username) is None:
            raise RunnerError("数据库连接账号格式无效", 64)
        if database not in (None, DATABASE):
            raise RunnerError("真实执行器只允许固定隔离库", 64)
        try:
            self.connection = pymysql.connect(
                host="127.0.0.1",
                port=13306,
                user=username,
                password=password.get_secret_value(),
                database=database,
                charset="utf8mb4",
                autocommit=True,
                connect_timeout=5,
                read_timeout=5,
                write_timeout=5,
            )
            # 管理入口也会写 owner；autocommit 下显式设 UTC，不改变服务器配置。
            self.execute("SET time_zone = '+00:00'")
            mode = self.query("SELECT @@SESSION.sql_mode")[0][0]
            if "NO_BACKSLASH_ESCAPES" in str(mode).split(","):
                raise RunnerError("会话 SQL 模式与字面量渲染不兼容", 64)
        except RunnerError:
            self.close()
            raise
        except Exception as error:
            self.close()
            raise RunnerError("数据库连接失败", 70, driver_error_code(error)) from None

    def execute(self, sql: str, params: tuple[object, ...] = ()) -> None:
        if self.state is not None:
            self.state.check()
        try:
            with self.connection.cursor() as cursor:
                # 空参数必须传 None，避免字面量内的百分号被客户端再次格式化。
                cursor.execute(sql, params if params else None)
                self.affected_rows = cursor.rowcount
        except Exception as error:
            raise RunnerError(
                "数据库语句执行失败", 70, driver_error_code(error)
            ) from None

    def query(self, sql: str, params: tuple[object, ...] = ()):
        try:
            with self.connection.cursor() as cursor:
                cursor.execute(sql, params if params else None)
                self.affected_rows = cursor.rowcount
                return cursor.fetchall()
        except Exception as error:
            raise RunnerError(
                "数据库只读查询失败", 70, driver_error_code(error)
            ) from None

    def close(self) -> None:
        if self.connection is not None and self.connection.open:
            self.connection.close()


def _redis_connection(password: SecretStr):
    from redis import Redis
    from redis.backoff import NoBackoff
    from redis.retry import Retry

    return Redis(
        host="127.0.0.1",
        port=16379,
        db=4,
        password=password.get_secret_value(),
        decode_responses=True,
        socket_connect_timeout=3,
        socket_timeout=3,
        retry=Retry(NoBackoff(), 0),
    )


def verify_server_ownership(environment: Mapping[str, str]) -> None:
    """fixture 仅用独立应用身份读取 owner；不读取真实 .env 或管理凭据。"""
    run_id = validate_child_environment(environment)
    url = make_url(environment["AUTH_INTEGRATION_DATABASE_URL"])
    redis_url = make_url(environment["AUTH_INTEGRATION_REDIS_URL"])
    database, redis = None, None
    try:
        database = PyMySqlExecutor(url.username, SecretStr(url.password), DATABASE)
        read_owner(database, run_id)
        redis = _redis_connection(SecretStr(redis_url.password))
        if redis.get(rate_limit_prefix(run_id) + ":owner") != run_id:
            raise RunnerError("Redis owner 缺失或与本轮不符", 65)
    except RunnerError:
        raise
    except Exception as error:
        raise RunnerError("服务端归属核验失败", 70, driver_error_code(error)) from None
    finally:
        if redis is not None:
            redis.close()
        if database is not None:
            database.close()


MIGRATION_WORKER = r"""
import contextlib
import io
import json
import os
import sys
from tools.auth_integration import driver_error_code, map_migration_environment
alembic_session_tz = None
try:
    os.environ.update(map_migration_environment(os.environ))
    with (
        contextlib.redirect_stdout(io.StringIO()),
        contextlib.redirect_stderr(io.StringIO()),
    ):
        from alembic import command
        from alembic.config import Config
        from sqlalchemy import event
        from sqlalchemy.engine import Engine

        @event.listens_for(Engine, "connect")
        def observe_migration_timezone(dbapi_connection, _connection_record):
            global alembic_session_tz
            # 读取实际迁移物理连接，不创建 SQLAlchemy Connection 的事务状态。
            with dbapi_connection.cursor() as cursor:
                cursor.execute("SELECT @@session.time_zone")
                observed = cursor.fetchone()[0]
                dbapi_connection.rollback()
            alembic_session_tz = observed

        command.upgrade(Config("alembic.ini"), "head")
except BaseException as error:
    print(json.dumps({"exit_code": 1, "error_code": driver_error_code(error)}))
    sys.exit(1)
print(json.dumps({
    "exit_code": 0,
    "error_code": 0,
    "alembic_session_tz": alembic_session_tz,
}))
"""


def _run_migration(
    state: RunState, supervisor: ChildSupervisor, environment: dict[str, str]
) -> str:
    state.check()
    supervisor.child = subprocess.Popen(
        [sys.executable, "-B", "-c", MIGRATION_WORKER],
        cwd=BACKEND,
        env=environment,
        start_new_session=True,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    deadline = time.monotonic() + 60
    while True:
        if state.received_signal is not None:
            supervisor.stop()
            raise RunnerError("迁移被信号中断", state.signal_exit_code)
        try:
            output, _ = supervisor.child.communicate(timeout=0.2)
            break
        except subprocess.TimeoutExpired:
            if time.monotonic() >= deadline:
                supervisor.stop()
                raise RunnerError("迁移等待超时", 70) from None
    try:
        result = json.loads(output.strip())
    except (ValueError, TypeError):
        raise RunnerError("迁移子进程未返回有效结果", 70) from None
    if supervisor.child.returncode != 0 or result.get("exit_code") != 0:
        raise RunnerError("迁移失败", 70, result.get("error_code"))
    if result.get("alembic_session_tz") != "+00:00":
        raise RunnerError("迁移物理连接会话时区未确认 UTC", 65)
    supervisor.stop()
    return result["alembic_session_tz"]


async def _asyncmy_read_once(url) -> None:
    import asyncmy

    connection = None
    try:
        connection = await asyncmy.connect(
            host="127.0.0.1",
            port=13306,
            user=url.username,
            password=url.password,
            db=DATABASE,
            charset="utf8mb4",
            connect_timeout=5,
            autocommit=True,
        )
        async with connection.cursor() as cursor:
            await cursor.execute("SELECT COUNT(*) FROM users")
            await cursor.fetchone()
    finally:
        if connection is not None:
            connection.close()


def _container_snapshot() -> dict[str, str]:
    result = {}
    for name, port in (("mysql", "13306"), ("redis", "16379")):
        raw = subprocess.run(
            [
                "docker",
                "inspect",
                "--format",
                "{{json .State.Status}} {{json .Id}} {{json .NetworkSettings.Ports}}",
                f"oj-dev-{name}-1",
            ],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if raw.returncode:
            raise RunnerError("容器状态读取失败", 70, raw.returncode)
        status, identity, bindings = raw.stdout.strip().split(" ", 2)
        if json.loads(status) != "running":
            raise RunnerError("开发依赖容器未运行", 65)
        ports = json.loads(bindings)
        values = [
            binding for entries in ports.values() if entries for binding in entries
        ]
        if not any(
            v["HostIp"] == "127.0.0.1" and v["HostPort"] == port for v in values
        ):
            raise RunnerError("开发依赖未按批准的回环端口发布", 65)
        if any(v["HostIp"] != "127.0.0.1" for v in values):
            raise RunnerError("开发依赖存在非回环发布", 65)
        result[name] = json.loads(identity)
    return result


def _business_counts(executor: SqlExecutor) -> tuple[int, int, int, int]:
    from tools.check_db_schema import TABLE_ORDER

    placeholders = ",".join("%s" for _ in TABLE_ORDER)
    parameters = (DATABASE, *TABLE_ORDER)
    condition = f"WHERE TABLE_SCHEMA=%s AND TABLE_NAME IN ({placeholders})"
    queries = [
        "SELECT COUNT(*) FROM INFORMATION_SCHEMA.TABLES " + condition,
        "SELECT COUNT(*) FROM INFORMATION_SCHEMA.COLUMNS " + condition,
        "SELECT COUNT(*) FROM INFORMATION_SCHEMA.TABLE_CONSTRAINTS "
        + condition
        + " AND CONSTRAINT_TYPE='UNIQUE'",
        "SELECT COUNT(*) FROM INFORMATION_SCHEMA.TABLE_CONSTRAINTS "
        + condition
        + " AND CONSTRAINT_TYPE='FOREIGN KEY'",
    ]
    return tuple(executor.query(query, parameters)[0][0] for query in queries)


def _owned_redis_delete(redis, run_id: str, *, include_owner: bool) -> int:
    prefix = rate_limit_prefix(run_id)
    owner = prefix + ":owner"
    if redis.get(owner) != run_id:
        raise RunnerError("Redis owner 不符，拒绝清理", 65)
    for key in list(redis.scan_iter(match=prefix + ":*")):
        if key == owner:
            continue
        if redis.get(owner) != run_id:
            raise RunnerError("Redis owner 已变化，拒绝清理", 65)
        redis.unlink(key)
    if include_owner:
        if redis.get(owner) != run_id:
            raise RunnerError("Redis owner 已变化，拒绝清理", 65)
        redis.unlink(owner)
    return sum(1 for _ in redis.scan_iter(match=prefix + ":*"))


def schema_exists(executor: SqlExecutor) -> bool:
    return bool(
        executor.query(
            "SELECT COUNT(*) FROM INFORMATION_SCHEMA.SCHEMATA WHERE SCHEMA_NAME=%s",
            (DATABASE,),
        )[0][0]
    )


def _round_inventory(executor: SqlExecutor, run_id: str, host: str) -> dict[str, int]:
    result = {DATABASE: int(schema_exists(executor))}
    for name in account_names(run_id):
        result[name + "@" + host] = executor.query(
            "SELECT COUNT(*) FROM mysql.user WHERE user=%s AND host=%s", (name, host)
        )[0][0]
    return result


def save_evidence(directory: Path, report: dict) -> None:
    # 先持久化再允许删除；只序列化显式构造的对象名、计数及错误码。
    temporary = directory / "report.tmp"
    with temporary.open("w", encoding="utf-8") as output:
        json.dump(report, output, ensure_ascii=False, indent=2)
        output.write("\n")
        output.flush()
        os.fsync(output.fileno())
    temporary.replace(directory / "report.json")
    descriptor = os.open(directory, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def cleanup_owned_resources(database, redis, state, host):
    """每种资源独立核验；一处缺失/失败不扩大删除授权，也不阻止另一处核验。"""
    errors = []
    try:
        if schema_exists(database):
            owner = read_owner(database, state.run_id)
            names = cleanup_account_names(owner, state.run_id)
            for name, role, code in zip(
                names, ("application", "migration"), ("a", "m"), strict=True
            ):
                rows = database.query(
                    "SELECT ATTRIBUTE FROM INFORMATION_SCHEMA.USER_ATTRIBUTES "
                    "WHERE USER=%s AND HOST=%s",
                    (name, host),
                )
                # 第二个建号失败允许第一个已归属账号被清理；缺失不伪装创建成功。
                if not rows:
                    continue
                if len(rows) != 1 or json.loads(rows[0][0]) != {
                    "oj_auth_check_run_id": state.run_id,
                    "role": role,
                }:
                    raise RunnerError("账号归属不符，保留 MySQL 资源", 65)
                database.execute(
                    "DROP USER " + account_literal(owner.run_id, code, host)
                )
            read_owner(database, state.run_id)
            database.execute("DROP DATABASE `oj_auth_check`")
        elif any(_round_inventory(database, state.run_id, host).values()):
            raise RunnerError("账号存在但缺少数据库 owner，保留账号", 65)
    except Exception as error:
        errors.append(
            ("mysql", driver_error_code(error) or getattr(error, "exit_code", 70))
        )
    try:
        prefix = rate_limit_prefix(state.run_id)
        if redis.get(prefix + ":owner") is not None:
            if _owned_redis_delete(redis, state.run_id, include_owner=True):
                raise RunnerError("Redis 残留", 65)
        elif next(iter(redis.scan_iter(match=prefix + ":*")), None) is not None:
            raise RunnerError("Redis 缺少 owner，保留键", 65)
    except Exception as error:
        errors.append(
            ("redis", driver_error_code(error) or getattr(error, "exit_code", 70))
        )
    return errors


def finish_round(state, supervisor, database, redis, host, directory, report):
    # 先停进程，再持久化现场，最后清理。失败时不进入后续删除阶段。
    supervisor.stop()
    save_evidence(directory, report)
    if state.resources_started:
        database.state = None  # 已停止业务；中断不应打断归属核验后的安全回收。
        report["cleanup_errors"] = cleanup_owned_resources(database, redis, state, host)
        report["inventory_after"] = _round_inventory(database, state.run_id, host)
        report["redis_remaining"] = sum(
            1 for _ in redis.scan_iter(match=rate_limit_prefix(state.run_id) + ":*")
        )
    save_evidence(directory, report)


def first_database_round(state, credentials, supervisor, *, run_tests=False) -> int:
    """完整生命周期只有此处编排；run_tests=False 仅用于第一轮环境往返。"""
    import asyncio
    import secrets

    from sqlalchemy.engine import URL

    directory = evidence_directory(state)
    directory.mkdir(parents=True)
    report = {
        "run_id": state.run_id,
        "suite": state.suite,
        "events": [],
        "exit_code": 70,
        "development_before": None,
        "development_after": None,
        "containers_after": None,
        "development_unchanged": None,
    }
    database, redis, host, baseline = None, None, None, None
    result = 0
    category = "PREFLIGHT"

    def event(kind, name, count=0):
        item = {"category": kind, "object": name, "count": count}
        report["events"].append(item)
        print(json.dumps(item, ensure_ascii=False), flush=True)

    try:
        state.check()
        baseline = _container_snapshot()
        database = PyMySqlExecutor("root", credentials.mysql_password, state=state)
        # 这是 SET 后的管理会话回读；独立 docker exec 默认会话证据另存，不能互相代替。
        category = "MANAGEMENT_SESSION_UTC"
        report["management_session_tz"] = database.query("SELECT @@session.time_zone")[
            0
        ][0]
        if report["management_session_tz"] != "+00:00":
            raise RunnerError("管理连接会话时区未确认 UTC", 65)
        event(category, "mysql", 1)
        category = "PREFLIGHT"
        redis = _redis_connection(credentials.redis_password)
        if not redis.ping():
            raise RunnerError("Redis PING 未通过", 65)
        version = database.query("SELECT VERSION()")[0][0]
        if version != "8.0.46":
            raise RunnerError("服务端版本不符", 65)
        development_before = read_development_snapshot(database)
        report["development_before"] = development_snapshot_values(development_before)
        if development_before != DevelopmentSnapshot(0, None):
            raise RunnerError("开发库基线变化", 65)
        host = validate_account_host(
            database.query("SELECT SUBSTRING_INDEX(USER(), '@', -1)")[0][0]
        )
        report["account_host"] = host
        report["containers_before"] = baseline
        if schema_exists(database):
            raise RunnerError("隔离库已存在，拒绝接管或重置", 65)
        event("PREFLIGHT", "mysql:8.0.46,oj:0,redis/db4," + host)
        state.check()
        state.resources_started = True
        category = "CREATE_DATABASE"
        create_isolated_database(database)
        event(category, DATABASE)
        category = "OWNER"
        create_owner_table(database)
        write_owner(database, state.run_id)
        event(category, DATABASE + ".__auth_check_owner")
        app_password, migration_password = (
            SecretStr(secrets.token_hex(32)),
            SecretStr(secrets.token_hex(32)),
        )
        category = "CREATE_USER"
        create_test_accounts(
            database, state.run_id, app_password, migration_password, host=host
        )
        for name in account_names(state.run_id):
            event(category, name + "@" + host)
        category = "GRANT_MIGRATION"
        grant_migration_account(database, state.run_id, host=host)
        event(category, account_name(state.run_id, "m"))
        migration_url = URL.create(
            "mysql+pymysql",
            username=account_name(state.run_id, "m"),
            password=migration_password.get_secret_value(),
            host="127.0.0.1",
            port=13306,
            database=DATABASE,
        ).render_as_string(hide_password=False)
        category = "MIGRATE"
        report["alembic_session_tz"] = _run_migration(
            state, supervisor, build_migration_environment(state.run_id, migration_url)
        )
        event("PYMYSQL_MIGRATION", "head")
        category = "METADATA_COUNTS"
        counts = _business_counts(database)
        report["business_counts"] = counts
        if counts != (9, 84, 6, 12):
            raise RunnerError("迁移结构计数不符", 65)
        event("SCHEMA_COUNTS", "tables,columns,unique,foreign", counts)
        category = "GRANT_APPLICATION"
        grant_application_account(database, state.run_id, host=host, suite=state.suite)
        event(category, account_name(state.run_id, "a"))
        app_url = URL.create(
            "mysql+asyncmy",
            username=account_name(state.run_id, "a"),
            password=app_password.get_secret_value(),
            host="127.0.0.1",
            port=13306,
            database=DATABASE,
        )
        category = "ASYNCMY_SELECT"
        state.check()
        asyncio.run(_asyncmy_read_once(app_url))
        event(category, "users", 1)
        category = "REDIS_PROBE"
        prefix = rate_limit_prefix(state.run_id)
        state.check()
        if not redis.set(prefix + ":owner", state.run_id, nx=True):
            raise RunnerError("Redis owner 已存在", 65)
        state.check()
        redis.set(prefix + ":probe", "1", ex=60)
        state.check()
        if _owned_redis_delete(redis, state.run_id, include_owner=False) != 1:
            raise RunnerError("Redis 探针残留", 65)
        event(category, prefix + ":probe", 0)
        redis_url = URL.create(
            "redis",
            username="default",
            password=credentials.redis_password.get_secret_value(),
            host="127.0.0.1",
            port=16379,
            database="4",
        ).render_as_string(hide_password=False)
        environment = build_child_environment(
            state.run_id,
            app_url.render_as_string(hide_password=False),
            redis_url,
            secrets.token_hex(32),
        )
        category = "OWNERSHIP"
        state.check()
        verify_server_ownership(environment)
        event(category, "mysql,redis", 1)
        if run_tests:
            category = "AUTH_TESTS" if state.suite == "auth" else "M1_TESTS"
            result = supervisor.run_pytest(environment)
            report["tests"] = supervisor.test_summary
            event(category, suite_test_file(state.suite), result)
            if result:
                raise RunnerError("隔离集成测试失败；不输出捕获内容", result)
        state.check()
    except Exception as error:
        result = getattr(error, "exit_code", 70)
        report["failure"] = {
            "category": category,
            "error_type": type(error).__name__,
            "error_code": driver_error_code(error)
            or getattr(error, "driver_code", None)
            or result,
        }
        event("FAILURE", category, report["failure"]["error_code"])
    finally:
        report["exit_code"] = state.signal_exit_code or result
        try:
            finish_round(state, supervisor, database, redis, host, directory, report)
            if baseline is not None and database is not None:
                report["development_after"] = development_snapshot_values(
                    read_development_snapshot(database)
                )
                if report["development_before"] is not None:
                    report["development_unchanged"] = (
                        report["development_before"] == report["development_after"]
                    )
                report["containers_after"] = _container_snapshot()
                if report["development_unchanged"] is False:
                    raise RunnerError("开发库收尾基线不符", 65)
                if report["containers_after"] != baseline:
                    raise RunnerError("容器身份改变", 65)
            if (
                report.get("cleanup_errors")
                or any(report.get("inventory_after", {}).values())
                or report.get("redis_remaining", 0)
            ):
                result = result or 70
        except Exception as error:
            report["finalization_error"] = driver_error_code(error) or getattr(
                error, "exit_code", 70
            )
            result = result or 70
        finally:
            for connection in (redis, database):
                if connection is not None:
                    try:
                        connection.close()
                    except Exception:
                        result = result or 70
        report["exit_code"] = state.signal_exit_code or result
        try:
            save_evidence(directory, report)
        except Exception:
            result = result or 70
        event(
            "FINAL", str(directory.relative_to(ROOT)), state.signal_exit_code or result
        )
    return state.signal_exit_code or result


if __name__ == "__main__":
    raise SystemExit(main())
