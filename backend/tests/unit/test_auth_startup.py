import importlib
from contextlib import contextmanager

import asyncmy
import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr, ValidationError
from redis.asyncio.connection import Connection

from app.core.config import Settings
from app.main import create_app


def configured(**changes):
    values = {
        "database_url": "mysql+asyncmy://placeholder:placeholder@127.0.0.1:1/offline",
        "redis_url": "redis://127.0.0.1:1/4",
        "jwt_secret": "startup-only-key-with-at-least-32-bytes",
    }
    values.update(changes)
    return Settings(**values)


def test_module_import_does_not_read_environment(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("导入期禁止读取配置")

    with monkeypatch.context() as patch:
        patch.setattr(Settings, "__init__", forbidden)
        module = importlib.reload(importlib.import_module("app.main"))
        assert module.app is not None


def test_lifespan_and_healthz_construct_resources_without_connections(monkeypatch):
    async def forbidden(*args, **kwargs):
        raise AssertionError("离线启动和 healthz 不允许建立外部连接")

    monkeypatch.setattr(asyncmy, "connect", forbidden)
    monkeypatch.setattr(Connection, "connect", forbidden)
    with TestClient(create_app(configured())) as client:
        assert client.get("/healthz").json() == {"status": "ok"}


@contextmanager
def unwrap_runtime_error():
    try:
        yield
    except ExceptionGroup as group:
        # 不绑定 Starlette/AnyIO 是否包装异常，但必须存在原始认证配置错误。
        matched, remainder = group.split(RuntimeError)
        if matched is None or remainder is not None:
            raise
        raise matched.exceptions[0] from None


def test_missing_secret_fails_startup_before_healthz(monkeypatch, caplog):
    for key in [
        "JWT_SECRET",
        "DATABASE_URL",
        "REDIS_URL",
        "JWT_EXPIRE_MINUTES",
        "RATE_LIMIT_KEY_PREFIX",
    ]:
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv(
        "DATABASE_URL", "mysql+asyncmy://placeholder:private-marker@127.0.0.1:1/offline"
    )
    monkeypatch.setenv("REDIS_URL", "redis://:private-marker@127.0.0.1:1/4")
    with (
        pytest.raises(RuntimeError, match="认证配置错误") as error,
        unwrap_runtime_error(),
        TestClient(create_app()),
    ):
        pytest.fail("配置缺失时不应启动")
    assert "private-marker" not in str(error.value) + caplog.text


def test_settings_hide_secret_and_validate_before_resource_creation():
    settings = configured()
    assert isinstance(settings.jwt_secret, SecretStr)
    with pytest.raises(ValidationError):
        configured(jwt_secret="short")
    with pytest.raises(ValidationError) as error:
        configured(database_url="mysql+pymysql://user:private-marker@host/db")
    assert "private-marker" not in str(error.value)
    for prefix in ["", "oj:", "contains whitespace"]:
        with pytest.raises(ValidationError):
            configured(rate_limit_key_prefix=prefix)


def test_settings_do_not_use_integration_configuration_by_default(monkeypatch):
    monkeypatch.setenv("AUTH_INTEGRATION_DATABASE_URL", "invalid")
    monkeypatch.setenv("AUTH_INTEGRATION_REDIS_URL", "invalid")
    assert configured().rate_limit_key_prefix == "oj:ratelimit:auth"


def test_redis_async_retry_is_zero_and_awaits_failure_cleanup():
    from unittest.mock import AsyncMock

    from redis.exceptions import ConnectionError

    app = create_app(configured())
    with TestClient(app) as client:
        retry = app.state.rate_limiter.redis.connection_pool.connection_kwargs["retry"]
        operation = AsyncMock(side_effect=ConnectionError("offline-synthetic-error"))
        cleanup = AsyncMock()

        async def exercise():
            # 直接执行 Retry 协议；不借连接。同步 Retry 不会等待异步失败清理。
            with pytest.raises(ConnectionError):
                await retry.call_with_retry(operation, cleanup)

        client.portal.call(exercise)
        assert retry.get_retries() == 0
        operation.assert_awaited_once()
        cleanup.assert_awaited_once()


# 锁定已批准的 30–60 分钟边界，避免配置模型又退回模板曾写的 1–60。
@pytest.mark.parametrize(
    ("minutes", "accepted"), [(29, False), (30, True), (60, True), (61, False)]
)
def test_jwt_expiry_accepts_only_approved_range(minutes, accepted):
    if accepted:
        assert configured(jwt_expire_minutes=minutes).jwt_expire_minutes == minutes
    else:
        with pytest.raises(ValidationError) as error:
            configured(jwt_expire_minutes=minutes)
        assert error.value.errors()[0]["loc"] == ("jwt_expire_minutes",)


# 07.5b 离线管理结构：所有执行器均为记录器，禁止连接真实依赖。
@pytest.fixture
def offline_auth_runner(monkeypatch):
    import socket

    from tools import auth_integration

    def forbidden(*args, **kwargs):
        raise AssertionError("离线管理测试禁止任何网络连接")

    monkeypatch.setattr(socket.socket, "connect", forbidden)
    monkeypatch.setattr(socket.socket, "connect_ex", forbidden)
    monkeypatch.setattr(socket, "getaddrinfo", forbidden)
    return auth_integration


@pytest.fixture
def integration_gate(offline_auth_runner):
    import importlib.util

    source = offline_auth_runner.BACKEND / "tests/integration/conftest.py"
    spec = importlib.util.spec_from_file_location("_offline_auth_gate", source)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def isolated_environment(runner):
    import uuid

    from sqlalchemy.engine import URL

    run_id = uuid.uuid4().hex
    app_user, _ = runner.account_names(run_id)
    url = URL.create(
        "mysql+asyncmy",
        username=app_user,
        password="offline-app-secret",
        host="127.0.0.1",
        port=13306,
        database="oj_auth_check",
    ).render_as_string(hide_password=False)
    return runner.build_child_environment(
        run_id,
        url,
        "redis://:offline-redis-secret@127.0.0.1:16379/4",
        "offline-key-with-at-least-thirty-two-bytes",
    )


def test_auth_child_environment_has_exact_keys(offline_auth_runner, monkeypatch):
    runner = offline_auth_runner
    monkeypatch.setenv("MYSQL_ROOT_PASSWORD", "offline-management-marker")
    monkeypatch.setenv("DATABASE_URL", "offline-development-marker")
    environment = isolated_environment(runner)
    assert set(environment) == runner.CHILD_ENV_KEYS
    assert "offline-management-marker" not in environment.values()
    assert runner.validate_child_environment(environment) == environment[
        "RATE_LIMIT_KEY_PREFIX"
    ].removeprefix(runner.PREFIX_ROOT)


@pytest.mark.parametrize("extra", ["MYSQL_ROOT_PASSWORD", "DATABASE_URL", "PATH"])
def test_auth_child_environment_rejects_extra_keys(offline_auth_runner, extra):
    runner = offline_auth_runner
    environment = isolated_environment(runner)
    environment[extra] = "offline-sensitive-extra"
    with pytest.raises(runner.RunnerError) as error:
        runner.validate_child_environment(environment)
    assert error.value.exit_code == 64
    assert "offline-sensitive-extra" not in str(error.value)


@pytest.mark.parametrize(
    "missing",
    [
        "AUTH_INTEGRATION_DATABASE_URL",
        "AUTH_INTEGRATION_REDIS_URL",
        "JWT_SECRET",
        "RATE_LIMIT_KEY_PREFIX",
    ],
)
def test_auth_child_environment_rejects_missing_keys(offline_auth_runner, missing):
    runner = offline_auth_runner
    environment = isolated_environment(runner)
    del environment[missing]
    with pytest.raises(runner.RunnerError) as error:
        runner.validate_child_environment(environment)
    assert error.value.exit_code == 64


def test_auth_gate_maps_before_test_import_and_fixture_only_reads_cache(
    offline_auth_runner, integration_gate, monkeypatch
):
    import inspect
    import os
    from types import SimpleNamespace

    from sqlalchemy.engine import make_url

    runner = offline_auth_runner
    gate = integration_gate
    environment = isolated_environment(runner)
    for name, value in environment.items():
        monkeypatch.setenv(name, value)
    for name in ["DATABASE_URL", "REDIS_URL", "DATABASE_URL_SYNC"]:
        monkeypatch.delenv(name, raising=False)
    # Settings 映射会改当前测试进程；登记完整快照，让 monkeypatch 在结束时恢复。
    monkeypatch.setattr(os, "environ", dict(os.environ))
    events = []
    original = gate.load_application_settings

    def map_once(values):
        events.append("map")
        return original(values)

    monkeypatch.setattr(
        gate, "require_server_ownership", lambda: events.append("owner")
    )
    monkeypatch.setattr(gate, "load_application_settings", map_once)
    config = SimpleNamespace(getoption=lambda _: True, stash={})
    gate.pytest_configure(config)
    # 模拟测试模块顶层代码：映射已经完成，顶层 Settings 也只能读到隔离目标。
    namespace = {}
    exec(
        "from app.main import app\n"
        "from app.core.config import Settings\n"
        "s = Settings()",
        namespace,
    )
    events.append("test_import")
    assert (
        make_url(namespace["s"].database_url.get_secret_value()).database
        == "oj_auth_check"
    )
    assert make_url(namespace["s"].redis_url.get_secret_value()).database == "4"
    cached = inspect.unwrap(gate.auth_integration_settings)(config)
    gate.pytest_configure(config)
    assert inspect.unwrap(gate.auth_integration_settings)(config) is cached
    assert events == ["owner", "map", "test_import"]


def test_auth_gate_failure_does_not_map(integration_gate, monkeypatch):
    from types import SimpleNamespace

    gate = integration_gate

    def reject():
        raise pytest.UsageError("offline owner rejected")

    def forbidden(*args):
        raise AssertionError("归属未通过，不得映射应用配置")

    monkeypatch.setattr(gate, "require_server_ownership", reject)
    monkeypatch.setattr(gate, "load_application_settings", forbidden)
    config = SimpleNamespace(getoption=lambda _: True, stash={})
    with pytest.raises(pytest.UsageError, match="offline owner rejected"):
        gate.pytest_configure(config)
    assert not config.stash


class RecordingAuthExecutor:
    # 记录真实交付给接口的 SQL/参数；响应由测试给定，不解析或执行任何 SQL。
    def __init__(self, *responses):
        self.calls = []
        self.responses = iter(responses)

    def execute(self, sql, params=()):
        self.calls.append(("execute", sql, params))

    def query(self, sql, params=()):
        self.calls.append(("query", sql, params))
        return next(self.responses)


def test_auth_database_and_owner_ddl_are_fixed(offline_auth_runner):
    runner = offline_auth_runner
    executor = RecordingAuthExecutor()
    runner.create_isolated_database(executor)
    runner.create_owner_table(executor)
    assert executor.calls[0] == (
        "execute",
        "CREATE DATABASE `oj_auth_check` "
        "CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci",
        (),
    )
    assert executor.calls[1] == (
        "execute",
        """CREATE TABLE `oj_auth_check`.`__auth_check_owner` (
    singleton TINYINT UNSIGNED NOT NULL PRIMARY KEY,
    run_id CHAR(32) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    app_user VARCHAR(32) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    migration_user VARCHAR(32) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    created_at DATETIME(3) NOT NULL,
    CONSTRAINT ck_auth_check_owner_singleton CHECK (singleton = 1)
) ENGINE=InnoDB""",
        (),
    )
    assert all("IF NOT EXISTS" not in sql for _, sql, _ in executor.calls)


@pytest.mark.parametrize("method", ["create_isolated_database", "create_owner_table"])
@pytest.mark.parametrize("target", ["oj", "oj_auth_check; DROP DATABASE oj"])
def test_auth_ddl_rejects_other_database_before_executor(
    offline_auth_runner, method, target
):
    runner = offline_auth_runner
    executor = RecordingAuthExecutor()
    with pytest.raises(runner.RunnerError) as error:
        getattr(runner, method)(executor, database=target)
    assert error.value.exit_code == 64
    assert executor.calls == []


@pytest.mark.parametrize(
    ("responses", "expected_versions"),
    [
        (([(0,)], [(0,)]), None),
        (([(10,)], [(1,)], [("0001_initial_schema",)]), ("0001_initial_schema",)),
        (([(1,)], [(1,)], []), ()),
    ],
)
def test_auth_development_snapshot_is_select_only(
    offline_auth_runner, responses, expected_versions
):
    runner = offline_auth_runner
    executor = RecordingAuthExecutor(*responses)
    result = runner.read_development_snapshot(executor)
    assert result.table_count == responses[0][0][0]
    assert result.versions == expected_versions
    assert executor.calls[:2] == [
        (
            "query",
            "SELECT COUNT(*) FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_SCHEMA = %s",
            ("oj",),
        ),
        (
            "query",
            "SELECT COUNT(*) FROM INFORMATION_SCHEMA.TABLES "
            "WHERE TABLE_SCHEMA = %s AND TABLE_NAME = %s",
            ("oj", "alembic_version"),
        ),
    ]
    if expected_versions is not None:
        assert executor.calls[2] == (
            "query",
            "SELECT version_num FROM `oj`.`alembic_version`",
            (),
        )
    assert all(
        kind == "query" and sql.startswith("SELECT ") for kind, sql, _ in executor.calls
    )


@pytest.mark.parametrize("count", [-1, "0", True])
def test_auth_snapshot_rejects_invalid_count(offline_auth_runner, count):
    runner = offline_auth_runner
    with pytest.raises(runner.RunnerError) as error:
        runner.read_development_snapshot(RecordingAuthExecutor([(count,)]))
    assert error.value.exit_code == 65


@pytest.mark.parametrize(
    "operation", ["create_owner_table", "read_development_snapshot"]
)
def test_auth_executor_errors_hide_password_and_driver_message(
    offline_auth_runner, operation
):
    import traceback

    runner = offline_auth_runner

    class BrokenExecutor:
        def execute(self, sql, params=()):
            raise RuntimeError("offline-password-and-connection-marker")

        query = execute

    with pytest.raises(runner.RunnerError) as error:
        getattr(runner, operation)(BrokenExecutor())
    rendered = str(error.value) + "".join(traceback.format_exception(error.value))
    assert "RuntimeError" in rendered
    assert "offline-password-and-connection-marker" not in rendered


def test_auth_accounts_encode_full_uuid_1000_samples(offline_auth_runner):
    import base64
    import re
    import uuid

    runner = offline_auth_runner
    for _ in range(1000):
        run_id = uuid.uuid4().hex
        names = runner.account_names(run_id)
        for role, name in zip(("a", "m"), names, strict=True):
            assert len(name) == 32
            assert re.fullmatch(r"oac_[am]_[a-z2-7]{26}", name)
            assert name == name.lower()
            assert (
                uuid.UUID(bytes=base64.b32decode(name[6:].upper() + "======")).hex
                == run_id
            )
            assert runner.validate_account_name(name, run_id, role) == name


@pytest.mark.parametrize("role", ["a", "m"])
def test_auth_account_rejects_tampering_at_every_position(offline_auth_runner, role):
    import uuid

    runner = offline_auth_runner
    run_id = uuid.uuid4().hex
    name = runner.account_name(run_id, role)
    for index, character in enumerate(name):
        replacement = "a" if character != "a" else "b"
        changed = name[:index] + replacement + name[index + 1 :]
        with pytest.raises(runner.RunnerError):
            runner.validate_account_name(changed, run_id, role)


@pytest.mark.parametrize(("role", "other"), [("a", "m"), ("m", "a")])
def test_auth_account_roles_cannot_be_interchanged(offline_auth_runner, role, other):
    import uuid

    runner = offline_auth_runner
    run_id = uuid.uuid4().hex
    with pytest.raises(runner.RunnerError) as error:
        runner.validate_account_name(runner.account_name(run_id, role), run_id, other)
    assert error.value.exit_code == 64


@pytest.mark.parametrize("upper_part", ["name", "run_id"])
def test_auth_account_rejects_uppercase(offline_auth_runner, upper_part):
    runner = offline_auth_runner
    run_id = "000000000000400080000000000000ab"
    name = runner.account_name(run_id, "a")
    with pytest.raises(runner.RunnerError):
        runner.validate_account_name(
            name.upper() if upper_part == "name" else name,
            run_id.upper() if upper_part == "run_id" else run_id,
            "a",
        )


def test_auth_account_rejects_noncanonical_padding_alias(offline_auth_runner):
    import base64
    import uuid

    runner = offline_auth_runner
    run_id = uuid.uuid4().hex
    name = runner.account_name(run_id, "a")
    alphabet = "abcdefghijklmnopqrstuvwxyz234567"
    alias = name[:-1] + alphabet[alphabet.index(name[-1]) + 1]
    # 末字符的无效 padding bits 可解出相同字节，仍必须拒绝这个不同的账号拼写。
    assert base64.b32decode(alias[6:].upper() + "======") == uuid.UUID(run_id).bytes
    with pytest.raises(runner.RunnerError):
        runner.validate_account_name(alias, run_id, "a")


def test_auth_builder_validator_and_cleanup_share_account_derivation(
    offline_auth_runner, monkeypatch
):
    runner = offline_auth_runner
    environment = isolated_environment(runner)
    run_id = environment["RATE_LIMIT_KEY_PREFIX"].removeprefix(runner.PREFIX_ROOT)
    original = runner.account_name
    seen = []

    def record(run_id, role):
        seen.append((run_id, role))
        return original(run_id, role)

    monkeypatch.setattr(runner, "account_name", record)
    runner.build_child_environment(
        run_id,
        environment["AUTH_INTEGRATION_DATABASE_URL"],
        environment["AUTH_INTEGRATION_REDIS_URL"],
        environment["JWT_SECRET"],
    )
    assert seen == [(run_id, "a")]
    seen.clear()
    runner.validate_child_environment(environment)
    assert seen == [(run_id, "a")]
    seen.clear()
    owner = runner.OwnerRecord(run_id, original(run_id, "a"), original(run_id, "m"))
    assert runner.cleanup_account_names(owner, run_id) == (
        original(run_id, "a"),
        original(run_id, "m"),
    )
    assert seen == [(run_id, "a"), (run_id, "m")]


def test_auth_account_create_sql_renders_password_and_full_run_id(offline_auth_runner):
    import json
    import uuid

    runner = offline_auth_runner
    run_id = uuid.uuid4().hex
    executor = RecordingAuthExecutor()
    passwords = ("offline-app-'secret", "offline-migration-secret")
    runner.create_test_accounts(executor, run_id, *(SecretStr(p) for p in passwords))
    names = runner.account_names(run_id)
    for call, name, password, role in zip(
        executor.calls, names, passwords, ("application", "migration"), strict=True
    ):
        kind, sql, params = call
        assert kind == "execute"
        attributes = json.dumps(
            {"oj_auth_check_run_id": run_id, "role": role}, sort_keys=True
        )
        assert sql == (
            f"CREATE USER '{name}'@'127.0.0.1' "
            f"IDENTIFIED WITH caching_sha2_password BY {runner.sql_literal(password)} "
            f"ATTRIBUTE {runner.sql_literal(attributes)}"
        )
        assert params == ()
        assert "%s" not in sql
        assert "IF NOT EXISTS" not in sql


@pytest.mark.parametrize(
    "invalid", ["plain-string-secret", SecretStr(""), SecretStr("bad\0value")]
)
def test_auth_account_validates_both_passwords_before_execute(
    offline_auth_runner, invalid
):
    import uuid

    runner = offline_auth_runner
    executor = RecordingAuthExecutor()
    with pytest.raises(runner.RunnerError) as error:
        runner.create_test_accounts(
            executor, uuid.uuid4().hex, SecretStr("valid-fake"), invalid
        )
    assert error.value.exit_code == 64
    assert "plain-string-secret" not in str(error.value)
    assert executor.calls == []


def test_auth_grants_are_separate_and_limited_to_fixed_schema(offline_auth_runner):
    import uuid

    runner = offline_auth_runner
    run_id = uuid.uuid4().hex
    app_user, migration_user = runner.account_names(run_id)
    executor = RecordingAuthExecutor()
    runner.grant_migration_account(executor, run_id)
    runner.grant_application_account(executor, run_id)
    assert executor.calls == [
        (
            "execute",
            "GRANT CREATE, ALTER, DROP, INDEX, REFERENCES, "
            "SELECT, INSERT, UPDATE, DELETE "
            f"ON `oj_auth_check`.* TO '{migration_user}'@'127.0.0.1'",
            (),
        ),
        (
            "execute",
            "GRANT SELECT, INSERT, UPDATE, DELETE ON `oj_auth_check`.`users` "
            f"TO '{app_user}'@'127.0.0.1'",
            (),
        ),
        (
            "execute",
            "GRANT SELECT ON `oj_auth_check`.`__auth_check_owner` "
            f"TO '{app_user}'@'127.0.0.1'",
            (),
        ),
    ]


def test_auth_owner_write_and_read_preserve_full_hex_run_id(offline_auth_runner):
    import uuid

    runner = offline_auth_runner
    run_id = uuid.uuid4().hex
    app_user, migration_user = runner.account_names(run_id)
    executor = RecordingAuthExecutor([(1, run_id, app_user, migration_user)])
    written = runner.write_owner(executor, run_id)
    actual = runner.read_owner(executor, run_id)
    assert actual == written == runner.OwnerRecord(run_id, app_user, migration_user)
    assert executor.calls == [
        (
            "execute",
            "INSERT INTO `oj_auth_check`.`__auth_check_owner` "
            "(singleton, run_id, app_user, migration_user, created_at) "
            "VALUES (1, %s, %s, %s, UTC_TIMESTAMP(3))",
            (run_id, app_user, migration_user),
        ),
        (
            "query",
            "SELECT singleton, run_id, app_user, migration_user "
            "FROM `oj_auth_check`.`__auth_check_owner`",
            (),
        ),
    ]
    assert runner.rate_limit_prefix(run_id) == "oj:ratelimit:auth-check:" + run_id


@pytest.mark.parametrize(
    "invalid",
    [
        "missing",
        "duplicate",
        "singleton",
        "bool_singleton",
        "run_id",
        "app_user",
        "roles",
        "shape",
    ],
)
def test_auth_owner_rejects_missing_or_wrong_ownership(offline_auth_runner, invalid):
    import uuid

    runner = offline_auth_runner
    run_id = uuid.uuid4().hex
    app_user, migration_user = runner.account_names(run_id)
    row = (1, run_id, app_user, migration_user)
    rows = [row]
    if invalid == "missing":
        rows = []
    elif invalid == "duplicate":
        rows = [row, row]
    elif invalid == "singleton":
        rows = [(2, *row[1:])]
    elif invalid == "bool_singleton":
        rows = [(True, *row[1:])]
    elif invalid == "run_id":
        rows = [(1, uuid.uuid4().hex, *row[2:])]
    elif invalid == "app_user":
        rows = [(1, run_id, "offline-other-account", migration_user)]
    elif invalid == "roles":
        rows = [(1, run_id, migration_user, app_user)]
    elif invalid == "shape":
        rows = [(1,)]
    with pytest.raises(runner.RunnerError) as error:
        runner.read_owner(RecordingAuthExecutor(rows), run_id)
    assert error.value.exit_code == 65
    assert "offline-other-account" not in str(error.value)


@pytest.mark.parametrize("mismatch", ["run_id", "stored_name"])
def test_auth_cleanup_derivation_refuses_stale_owner(offline_auth_runner, mismatch):
    import uuid

    runner = offline_auth_runner
    run_id = uuid.uuid4().hex
    app_user, migration_user = runner.account_names(run_id)
    owner = runner.OwnerRecord(
        uuid.uuid4().hex if mismatch == "run_id" else run_id,
        "offline-ledger-name" if mismatch == "stored_name" else app_user,
        migration_user,
    )
    with pytest.raises(runner.RunnerError) as error:
        runner.cleanup_account_names(owner, run_id)
    assert error.value.exit_code == 65


@pytest.mark.parametrize(
    "method",
    [
        "write_owner",
        "read_owner",
        "grant_migration_account",
        "grant_application_account",
    ],
)
def test_auth_management_helpers_refuse_development_database(
    offline_auth_runner, method
):
    import uuid

    runner = offline_auth_runner
    executor = RecordingAuthExecutor()
    with pytest.raises(runner.RunnerError) as error:
        getattr(runner, method)(executor, uuid.uuid4().hex, database="oj")
    assert error.value.exit_code == 64
    assert executor.calls == []


def test_auth_migration_channel_requires_encoded_migration_role(offline_auth_runner):
    import uuid

    from sqlalchemy.engine import URL

    runner = offline_auth_runner
    run_id = uuid.uuid4().hex
    app_user, migration_user = runner.account_names(run_id)

    def url(name):
        return URL.create(
            "mysql+pymysql",
            username=name,
            password="offline-migration-secret",
            host="127.0.0.1",
            port=13306,
            database="oj_auth_check",
        ).render_as_string(hide_password=False)

    safe = runner.build_migration_environment(run_id, url(migration_user))
    assert runner.map_migration_environment(safe) == {
        "DATABASE_URL_SYNC": url(migration_user)
    }
    with pytest.raises(runner.RunnerError):
        runner.build_migration_environment(run_id, url(app_user))


def test_auth_create_account_driver_error_cannot_echo_bound_password(
    offline_auth_runner,
):
    import traceback
    import uuid

    runner = offline_auth_runner
    marker = "offline-bound-account-password"

    class EchoingExecutor:
        def execute(self, sql, params=()):
            raise RuntimeError("driver printed statement: " + sql)

    with pytest.raises(runner.RunnerError) as error:
        runner.create_test_accounts(
            EchoingExecutor(),
            uuid.uuid4().hex,
            SecretStr(marker),
            SecretStr("offline-migration-password"),
        )
    assert marker not in str(error.value)
    assert marker not in "".join(traceback.format_exception(error.value))
    assert "RuntimeError" in str(error.value)


def test_auth_sql_literal_escapes_quotes_backslashes_and_hides_errors(
    offline_auth_runner,
):
    import traceback
    import uuid

    runner = offline_auth_runner
    raw = "offline-'quote\\path"
    assert runner.sql_literal(raw) == "'offline-''quote\\\\path'"
    executor = RecordingAuthExecutor()
    run_id = uuid.uuid4().hex
    runner.create_test_accounts(executor, run_id, SecretStr(raw), SecretStr(raw))
    assert all(
        "BY 'offline-''quote\\\\path' ATTRIBUTE " in sql for _, sql, _ in executor.calls
    )
    assert all(params == () for _, _, params in executor.calls)
    for host in ["%", "localhost", "127.0.0.1' OR '1'='1"]:
        with pytest.raises(runner.RunnerError):
            runner.account_literal(run_id, "a", host)

    class EchoingExecutor:
        def execute(self, sql, params=()):
            raise RuntimeError(raw + sql)

    with pytest.raises(runner.RunnerError) as error:
        runner.create_test_accounts(
            EchoingExecutor(), run_id, SecretStr(raw), SecretStr(raw)
        )
    assert raw not in str(error.value) + "".join(
        traceback.format_exception(error.value)
    )


def test_auth_attribute_json_is_valid_sql_literal(offline_auth_runner):
    import json

    runner = offline_auth_runner
    value = {"note": "double \"quote\", single 'quote', backslash \\"}
    encoded = json.dumps(value, sort_keys=True)
    literal = runner.sql_literal(encoded)
    assert literal.startswith("'") and literal.endswith("'")
    assert '"note"' in literal
    assert "''quote''" in literal
    # 只验证渲染往返，不把这个离线反解当作 MySQL 服务器执行证据。
    restored = literal[1:-1].replace("''", "'").replace("\\\\", "\\")
    assert json.loads(restored) == value


@pytest.mark.parametrize(
    "control", ["\0", "\n", "\r", "\t", "\x1f", "\x7f", "\x85", "\u202e"]
)
def test_auth_sql_literal_rejects_control_characters(offline_auth_runner, control):
    runner = offline_auth_runner
    value = "offline-control-secret" + control
    with pytest.raises(runner.RunnerError) as error:
        runner.sql_literal(value)
    assert error.value.exit_code == 64
    assert "offline-control-secret" not in str(error.value)


@pytest.mark.parametrize(
    "value",
    [
        "000000000000400080000000000000AB",
        "{00000000-0000-4000-8000-0000000000ab}",
        "123456781234123492341234567890ab",
        "0" * 31,
        "0" * 33,
        "g" * 32,
    ],
)
def test_auth_run_uuid_rejects_invalid_forms(offline_auth_runner, value):
    runner = offline_auth_runner
    with pytest.raises(runner.RunnerError) as error:
        runner._run_uuid(value)
    assert error.value.exit_code == 64
    assert value not in str(error.value)


@pytest.fixture
def auth_lifecycle(offline_auth_runner, monkeypatch, tmp_path):
    """用有状态替身执行完整编排；证明顺序/归属/故障分支，不冒充 SQL 解析。"""
    import json
    import uuid
    from types import SimpleNamespace

    runner = offline_auth_runner
    state = runner.RunState(uuid.uuid4().hex)
    events = []
    fault = {"write": None, "signal": None, "migration": False}

    class Database:
        def __init__(self):
            self.state = state
            self.exists = False
            self.owner = False
            self.users = {}
            self.writes = 0
            self.affected_rows = 1

        def execute(self, sql, params=()):
            if self.state is not None:
                self.state.check()
            self.writes += 1
            events.append(sql.split()[0:2])
            if fault["write"] == self.writes:
                raise runner.RunnerError("synthetic failure", 70, 1234)
            if sql.startswith("CREATE DATABASE"):
                self.exists = True
            elif sql.startswith("INSERT INTO"):
                self.owner = True
            elif sql.startswith("CREATE USER"):
                role = "a" if "oac_a_" in sql else "m"
                self.users[runner.account_name(state.run_id, role)] = {
                    "oj_auth_check_run_id": state.run_id,
                    "role": "application" if role == "a" else "migration",
                }
            elif sql.startswith("DROP USER"):
                name = next(n for n in self.users if n in sql)
                del self.users[name]
            elif sql.startswith("DROP DATABASE"):
                self.exists = self.owner = False
            if fault["signal"] == self.writes:
                state.receive_signal(15, None)

        def query(self, sql, params=()):
            if sql == "SELECT @@session.time_zone":
                return [("+00:00",)]
            if "@@SESSION" in sql:
                return [("STRICT_TRANS_TABLES",)]
            if "VERSION()" in sql:
                return [("8.0.46",)]
            if "USER()" in sql:
                return [("172.18.0.1",)]
            if "SCHEMATA" in sql:
                return [(int(self.exists),)]
            if sql == runner.READ_OWNER_SQL:
                return (
                    [(1, state.run_id, *runner.account_names(state.run_id))]
                    if self.owner
                    else []
                )
            if "USER_ATTRIBUTES" in sql:
                return (
                    [(json.dumps(self.users[params[0]]),)]
                    if params[0] in self.users
                    else []
                )
            if "mysql.user" in sql:
                return [(int(params[0] in self.users),)]
            return [(0,)]

        def close(self):
            pass

    class Redis:
        def __init__(self):
            self.keys = {}

        def ping(self):
            return True

        def set(self, key, value, **options):
            state.check()
            if options.get("nx") and key in self.keys:
                return False
            self.keys[key] = value
            return True

        def get(self, key):
            return self.keys.get(key)

        def scan_iter(self, **options):
            return iter(list(self.keys))

        def unlink(self, key):
            events.append(["REDIS", "UNLINK"])
            self.keys.pop(key, None)

        def close(self):
            pass

    database, redis = Database(), Redis()
    supervisor = SimpleNamespace(
        stop=lambda: events.append(["STOP"]), run_pytest=lambda env: 0
    )
    monkeypatch.setattr(runner, "ROOT", tmp_path)
    monkeypatch.setattr(
        runner, "_container_snapshot", lambda: {"mysql": "one", "redis": "two"}
    )
    monkeypatch.setattr(runner, "PyMySqlExecutor", lambda *a, **kw: database)
    monkeypatch.setattr(runner, "_redis_connection", lambda *a: redis)
    monkeypatch.setattr(runner, "_business_counts", lambda db: (9, 84, 6, 12))
    monkeypatch.setattr(runner, "verify_server_ownership", lambda env: None)

    async def handshake(url):
        pass

    def migration(*args):
        state.check()
        if fault["migration"]:
            raise runner.RunnerError("synthetic migration failure", 70, 1045)
        return "+00:00"

    monkeypatch.setattr(runner, "_asyncmy_read_once", handshake)
    monkeypatch.setattr(runner, "_run_migration", migration)
    original = runner.save_evidence

    def evidence(directory, report):
        events.append(["EVIDENCE"])
        original(directory, report)

    monkeypatch.setattr(runner, "save_evidence", evidence)
    credentials = runner.ManagementCredentials(
        SecretStr("fake-root"), SecretStr("fake-redis")
    )

    def run():
        return runner.first_database_round(state, credentials, supervisor)

    def report():
        return json.loads(
            (
                tmp_path
                / "local-reference/runtime/07.5b"
                / state.run_id
                / "report.json"
            ).read_text()
        )

    return SimpleNamespace(
        runner=runner,
        state=state,
        database=database,
        redis=redis,
        fault=fault,
        events=events,
        run=run,
        report=report,
    )


def test_auth_lifecycle_stops_and_saves_before_drop(auth_lifecycle):
    h = auth_lifecycle
    assert h.run() == 0
    assert (
        h.events.index(["STOP"])
        < h.events.index(["EVIDENCE"])
        < h.events.index(["DROP", "USER"])
    )
    assert not h.database.exists and not h.database.users and not h.redis.keys
    assert h.report()["account_host"] == "172.18.0.1"
    assert h.report()["management_session_tz"] == "+00:00"


def test_auth_partial_account_creation_is_owned_and_cleaned(auth_lifecycle):
    h = auth_lifecycle
    h.fault["write"] = 5  # 第二个 CREATE USER；第一个已成功。
    assert h.run() == 70
    assert h.report()["failure"]["error_code"] == 1234
    assert not h.database.exists and not h.database.users


def test_auth_migration_failure_keeps_error_and_cleans(auth_lifecycle):
    h = auth_lifecycle
    h.fault["migration"] = True
    assert h.run() == 70
    assert h.report()["failure"]["error_code"] == 1045
    assert not h.database.exists and not h.database.users


@pytest.mark.parametrize("write", range(1, 9))
def test_auth_interruption_prevents_next_business_write(auth_lifecycle, write):
    h = auth_lifecycle
    h.fault["signal"] = write
    assert h.run() == 143
    before_stop = h.events[: h.events.index(["STOP"])]
    assert (
        len([e for e in before_stop if e[0] in {"CREATE", "INSERT", "GRANT"}]) == write
    )
    if write >= 3:
        assert not h.database.exists and not h.database.users
    else:
        assert h.database.exists  # owner 不完整，不能凭本地状态删库。
        assert h.report()["cleanup_errors"]


def test_auth_evidence_failure_prevents_all_cleanup(auth_lifecycle, monkeypatch):
    h = auth_lifecycle

    def fail(*args):
        raise OSError("synthetic disk failure")

    monkeypatch.setattr(h.runner, "save_evidence", fail)
    assert h.run() == 70
    assert h.database.exists and len(h.database.users) == 2
    assert not any(e[0] == "DROP" for e in h.events)


def test_auth_bad_mysql_owner_does_not_block_owned_redis_cleanup(
    auth_lifecycle, monkeypatch
):
    h = auth_lifecycle

    def reject(*args):
        raise h.runner.RunnerError("owner mismatch", 65)

    monkeypatch.setattr(h.runner, "read_owner", reject)
    assert h.run() == 70
    assert h.database.exists and h.database.users
    assert not h.redis.keys


def test_auth_partial_cleanup_failure_is_reported(auth_lifecycle):
    h = auth_lifecycle
    h.fault["write"] = 10  # 第二个 DROP USER；保留 owner 以便人工恢复。
    assert h.run() == 70
    assert h.database.exists and len(h.database.users) == 1
    assert h.report()["cleanup_errors"] == [["mysql", 70]]
    assert not h.redis.keys


def test_auth_process_stop_failure_prevents_cleanup(auth_lifecycle, monkeypatch):
    h = auth_lifecycle

    def fail(*args):
        raise h.runner.RunnerError("process still alive", 70)

    monkeypatch.setattr(h.runner, "finish_round", fail)
    assert h.run() == 70
    assert h.database.exists and len(h.database.users) == 2
    assert not any(e[0] == "DROP" for e in h.events)


def test_auth_wrong_redis_owner_preserves_keys_but_cleans_mysql(
    auth_lifecycle, monkeypatch
):
    h = auth_lifecycle

    def mismatch(environment):
        h.redis.keys[h.runner.rate_limit_prefix(h.state.run_id) + ":owner"] = "foreign"
        raise h.runner.RunnerError("owner mismatch", 65)

    monkeypatch.setattr(h.runner, "verify_server_ownership", mismatch)
    assert h.run() == 65
    assert not h.database.exists and not h.database.users
    assert h.redis.keys
    assert h.report()["cleanup_errors"] == [["redis", 65]]


@pytest.mark.parametrize("signum", [2, 15])
def test_auth_real_process_group_is_reaped(offline_auth_runner, signum):
    """启动真实父子进程；组信号后父进程回收子进程，确认整个进程组消失。"""
    import os
    import subprocess
    import sys
    import uuid

    runner = offline_auth_runner
    state = runner.RunState(uuid.uuid4().hex)
    supervisor = runner.ChildSupervisor(state)
    source = """
import subprocess, sys, signal, time
child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(30)'])
def stop(signum, frame):
    child.wait(timeout=5)
    sys.exit(128 + signum)
signal.signal(signal.SIGINT, stop)
signal.signal(signal.SIGTERM, stop)
print('ready', flush=True)
while True:
    time.sleep(.1)
"""
    supervisor.child = subprocess.Popen(
        [sys.executable, "-B", "-c", source],
        start_new_session=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
    )
    group = supervisor.child.pid
    try:
        assert supervisor.child.stdout.readline().strip() == "ready"
        state.receive_signal(signum, None)
        supervisor.stop()
        assert state.signal_exit_code == 128 + signum
        assert supervisor.child is None
        with pytest.raises(ProcessLookupError):
            os.killpg(group, 0)
    finally:
        supervisor.stop()


def test_auth_foreign_attribute_blocks_database_drop(auth_lifecycle, monkeypatch):
    h = auth_lifecycle

    def corrupt(environment):
        name = h.runner.account_name(h.state.run_id, "a")
        h.database.users[name]["oj_auth_check_run_id"] = "foreign"

    monkeypatch.setattr(h.runner, "verify_server_ownership", corrupt)
    assert h.run() == 70
    assert h.database.exists and len(h.database.users) == 2
    assert not h.redis.keys


def test_auth_cli_file_path_imports_schema_checker_without_pytest_path(
    offline_auth_runner, tmp_path
):
    """子解释器模拟脚本目录 sys.path，执行原结构核验函数；不替换该函数。"""
    import subprocess
    import sys

    runner = offline_auth_runner
    source = """
import runpy, socket, sys
from pathlib import Path
def forbidden(*args, **kwargs):
    raise AssertionError('network forbidden')
socket.socket.connect = forbidden
socket.getaddrinfo = forbidden
sys.path[0] = str(Path(sys.argv[1]).parent)
module = runpy.run_path(sys.argv[1], run_name='_offline_cli')
class Database:
    def __init__(self):
        self.calls = []
        self.results = iter((9, 84, 6, 12))
    def query(self, sql, params):
        assert params[0] == 'oj_auth_check'
        assert len(params) == 10
        self.calls.append(sql)
        return [(next(self.results),)]
db = Database()
assert module['_business_counts'](db) == (9, 84, 6, 12)
assert len(db.calls) == 4
print('file-path-import-ok')
"""
    result = subprocess.run(
        [
            sys.executable,
            "-B",
            "-c",
            source,
            str(runner.BACKEND / "tools/auth_integration.py"),
        ],
        cwd=tmp_path,
        env={},
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "file-path-import-ok"


@pytest.mark.parametrize("argument,code", [("--help", 0), ("--unknown", 2)])
def test_auth_cli_arguments_do_not_require_configuration(
    offline_auth_runner, tmp_path, argument, code
):
    import subprocess
    import sys

    runner = offline_auth_runner
    result = subprocess.run(
        [
            sys.executable,
            "-B",
            str(runner.BACKEND / "tools/auth_integration.py"),
            argument,
        ],
        cwd=tmp_path,
        env={},
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode == code
    assert "--unknown" not in result.stderr


@pytest.mark.parametrize(
    "output,exit_code,rejected",
    [
        ("7 passed in 1s", 0, False),
        ("no tests ran", 0, True),
        ("6 passed, 1 skipped", 0, True),
        ("1 failed", 1, False),
    ],
)
def test_auth_child_result_and_environment_contract(
    offline_auth_runner, monkeypatch, output, exit_code, rejected
):
    from types import SimpleNamespace

    runner = offline_auth_runner
    environment = isolated_environment(runner)
    state = runner.RunState(runner.validate_child_environment(environment))
    supervisor = runner.ChildSupervisor(state)
    observed = {}

    def start(*args, **kwargs):
        observed.update(kwargs)
        return SimpleNamespace(
            returncode=exit_code, communicate=lambda **kw: (output, None)
        )

    monkeypatch.setattr(runner.subprocess, "Popen", start)
    if rejected:
        with pytest.raises(runner.RunnerError):
            supervisor.run_pytest(environment)
    else:
        assert supervisor.run_pytest(environment) == exit_code
    assert set(observed["env"]) == runner.CHILD_ENV_KEYS
    assert observed["start_new_session"] is True


def test_auth_management_connection_sets_utc_and_sanitizes_failure(
    offline_auth_runner, monkeypatch
):
    """替换驱动连接而非 execute 方法，锁住真实初始化调用及失败关闭责任。"""
    import traceback

    import pymysql

    runner = offline_auth_runner
    connections, options = [], []
    fail_set = False

    class Connection:
        open = True

        def __init__(self):
            self.calls = []

        def cursor(self):
            return Cursor(self)

        def close(self):
            self.open = False

    class Cursor:
        rowcount = 0

        def __init__(self, connection):
            self.connection = connection

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def execute(self, sql, params):
            self.connection.calls.append(sql)
            if fail_set and sql.startswith("SET "):
                raise pymysql.err.OperationalError(
                    1298, "offline-sensitive-driver-text"
                )

        def fetchall(self):
            return [("STRICT_TRANS_TABLES",)]

    def connect(**kwargs):
        options.append(kwargs)
        connection = Connection()
        connections.append(connection)
        return connection

    monkeypatch.setattr(pymysql, "connect", connect)
    executor = runner.PyMySqlExecutor("root", SecretStr("offline-root-password"))
    assert options[0]["autocommit"] is True
    assert connections[0].calls == [
        "SET time_zone = '+00:00'",
        "SELECT @@SESSION.sql_mode",
    ]
    executor.close()
    fail_set = True
    with pytest.raises(runner.RunnerError) as error:
        runner.PyMySqlExecutor("root", SecretStr("offline-root-password"))
    assert error.value.exit_code == 70 and error.value.driver_code == 1298
    assert not connections[1].open
    assert "offline-sensitive-driver-text" not in "".join(
        traceback.format_exception(error.value)
    )


def test_auth_alembic_environment_keeps_pool_timeout_and_utc(offline_auth_runner):
    """静态锁住既有迁移配置，不导入 env.py，不运行 Alembic 或修改其正文。"""
    import ast

    source = offline_auth_runner.BACKEND / "alembic/env.py"
    tree = ast.parse(source.read_text())
    online = next(
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == "run_migrations_online"
    )
    calls = [
        node
        for node in ast.walk(online)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "create_engine"
    ]
    assert len(calls) == 1
    keywords = {keyword.arg: keyword.value for keyword in calls[0].keywords}
    assert ast.unparse(keywords["poolclass"]) == "pool.NullPool"
    arguments = ast.literal_eval(keywords["connect_args"])
    assert arguments["init_command"] == "SET time_zone = '+00:00'"
    assert arguments["connect_timeout"] == 5


def test_auth_migration_result_requires_observed_utc(offline_auth_runner, monkeypatch):
    """成功退出不等于已测时区；父进程必须拒绝字段缺失或非 UTC 的 JSON。"""
    import json
    import uuid
    from types import SimpleNamespace

    runner = offline_auth_runner
    state = runner.RunState(uuid.uuid4().hex)
    for value in [None, "+08:00", "+00:00"]:
        payload = {"exit_code": 0, "error_code": 0}
        if value is not None:
            payload["alembic_session_tz"] = value
        child = SimpleNamespace(
            returncode=0,
            communicate=lambda payload=payload, **kw: (json.dumps(payload), ""),
        )
        stopped = []
        supervisor = SimpleNamespace(
            child=None, stop=lambda stopped=stopped: stopped.append(True)
        )
        monkeypatch.setattr(
            runner.subprocess, "Popen", lambda *a, child=child, **kw: child
        )
        if value != "+00:00":
            with pytest.raises(runner.RunnerError) as error:
                runner._run_migration(state, supervisor, {})
            assert error.value.exit_code == 65
        else:
            assert runner._run_migration(state, supervisor, {}) == "+00:00"
            assert stopped == [True]


@pytest.mark.parametrize("failure_at", ["query", "rollback"])
def test_auth_migration_listener_exception_fails_worker_closed(
    offline_auth_runner, monkeypatch, capsys, failure_at
):
    """执行真实 worker 脚本，替换迁移/DBAPI 边界，验证监听器异常不能产生成功 JSON。"""
    import json

    from sqlalchemy import event
    from sqlalchemy.engine import Engine

    from alembic import command

    runner = offline_auth_runner
    listeners, actions = [], []
    marker = "offline-sensitive-probe-exception"

    def listens_for(target, name):
        assert target is Engine and name == "connect"

        def register(callback):
            listeners.append(callback)
            return callback

        return register

    class Cursor:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            actions.append("cursor_closed")

        def execute(self, sql):
            assert sql == "SELECT @@session.time_zone"
            actions.append("query")
            if failure_at == "query":
                raise RuntimeError(marker)

        def fetchone(self):
            actions.append("fetch")
            return ("+00:00",)

    class Connection:
        def cursor(self):
            return Cursor()

        def rollback(self):
            actions.append("rollback")
            if failure_at == "rollback":
                raise RuntimeError(marker)

    def upgrade(*args):
        assert len(listeners) == 1
        listeners[0](Connection(), object())
        pytest.fail("监听器异常不得被吞掉")

    monkeypatch.setattr(runner, "map_migration_environment", lambda environment: {})
    monkeypatch.setattr(event, "listens_for", listens_for)
    monkeypatch.setattr(command, "upgrade", upgrade)
    with pytest.raises(SystemExit) as error:
        exec(runner.MIGRATION_WORKER, {})
    captured = capsys.readouterr()
    assert error.value.code == 1
    payload = json.loads(captured.out)
    assert payload == {"exit_code": 1, "error_code": None}
    assert marker not in captured.out + captured.err
    assert actions[-1] == "cursor_closed"
    if failure_at == "rollback":
        assert actions == ["query", "fetch", "rollback", "cursor_closed"]


@pytest.mark.parametrize("process_code,worker_code", [(1, 1), (1, 0), (0, 1)])
def test_auth_migration_worker_failure_cannot_report_success(
    offline_auth_runner, monkeypatch, process_code, worker_code
):
    """进程状态或 JSON 任一失败，即使附带 UTC 值也必须由父进程拒绝。"""
    import json
    import uuid
    from types import SimpleNamespace

    runner = offline_auth_runner
    payload = {
        "exit_code": worker_code,
        "error_code": 1213,
        "alembic_session_tz": "+00:00",
    }
    child = SimpleNamespace(
        returncode=process_code, communicate=lambda **kwargs: (json.dumps(payload), "")
    )
    supervisor = SimpleNamespace(child=None, stop=lambda: None)
    monkeypatch.setattr(runner.subprocess, "Popen", lambda *args, **kwargs: child)
    with pytest.raises(runner.RunnerError) as error:
        runner._run_migration(runner.RunState(uuid.uuid4().hex), supervisor, {})
    assert error.value.exit_code == 70 and error.value.driver_code == 1213


def test_auth_non_utc_management_readback_rejects_before_create(
    auth_lifecycle, monkeypatch
):
    h = auth_lifecycle
    original = h.database.query

    def wrong_timezone(sql, params=()):
        if sql == "SELECT @@session.time_zone":
            return [("+08:00",)]
        return original(sql, params)

    monkeypatch.setattr(h.database, "query", wrong_timezone)
    assert h.run() == 65
    assert h.report()["management_session_tz"] == "+08:00"
    assert h.report()["failure"]["category"] == "MANAGEMENT_SESSION_UTC"
    assert not any(event[0] == "CREATE" for event in h.events)
    assert not h.database.exists and not h.database.users and not h.redis.keys
