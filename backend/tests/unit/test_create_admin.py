"""管理员命令的离线契约：真实密码算法配合会话替身，不建立 MySQL/Redis 连接。"""

from contextlib import asynccontextmanager
from io import StringIO
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from asyncmy.errors import IntegrityError as DriverIntegrityError
from pydantic import SecretStr
from sqlalchemy.exc import IntegrityError, OperationalError

from app.repositories.user import UserRepository
from app.schemas.auth import RegisterRequest
from tools import create_admin as admin

PASSWORD = "unit-only-password-with-spaces  "
URL = "mysql+asyncmy://offline:offline@127.0.0.1:1/offline"


@pytest.fixture
def anyio_backend():
    return "asyncio"


class Terminal(StringIO):
    def isatty(self):
        return True


# 只记录调用顺序及 pending/committed 状态；不能用它证明数据库实际回滚或并发唯一性。
class Session:
    def __init__(self, failure_stage=None, error=None):
        self.events = []
        self.pending = []
        self.committed = []
        self.failure_stage = failure_stage
        self.error = error or RuntimeError("private-driver-marker")

    def fail_at(self, stage):
        if self.failure_stage == stage:
            raise self.error

    @asynccontextmanager
    async def begin(self):
        self.events.append("begin")
        try:
            yield
            self.fail_at("commit")
            self.committed.extend(self.pending)
            self.pending.clear()
            self.events.append("commit")
        except BaseException:
            self.pending.clear()
            self.events.append("rollback")
            raise

    def add(self, user):
        self.events.append("add")
        self.pending.append(user)

    async def flush(self):
        self.events.append("flush")
        self.fail_at("flush")

    async def refresh(self, user):
        self.events.append("refresh")
        self.fail_at("refresh")
        user.id = 7


def integrity_error(code=1062, key="users.uk_users_username"):
    return IntegrityError(
        "INSERT", {}, DriverIntegrityError(code, f"private-value for key '{key}'")
    )


def fake_hash(monkeypatch, session):
    async def hash_password(password, *, ctx):
        session.events.append("hash")
        return "unit-encoded-hash"

    monkeypatch.setattr(admin, "hash_password", hash_password)


def test_interactive_password_confirmation_ignores_environment(monkeypatch):
    replies = iter([PASSWORD, PASSWORD])
    monkeypatch.setattr(admin.getpass, "getpass", lambda prompt: next(replies))
    assert (
        admin.read_admin_password(
            {"OJ_ADMIN_PASSWORD": "must-not-use-this"}, Terminal()
        )
        == PASSWORD
    )


@pytest.mark.parametrize("failure", ["mismatch", "warning", "eof"])
def test_interactive_input_fails_without_echo_fallback(monkeypatch, failure):
    def read(prompt):
        if failure == "warning":
            admin.warnings.warn("private-warning-marker", admin.getpass.GetPassWarning)
        if failure == "eof":
            raise EOFError("private-eof-marker")
        return "first" if "再次" not in prompt else "second"

    monkeypatch.setattr(admin.getpass, "getpass", read)
    with pytest.raises(admin.CommandError) as error:
        admin.read_admin_password({}, Terminal())
    assert error.value.exit_code == 2
    assert "private-" not in str(error.value)


def test_noninteractive_password_source_and_history_notice(capsys):
    assert (
        admin.read_admin_password({"OJ_ADMIN_PASSWORD": PASSWORD}, StringIO())
        == PASSWORD
    )
    captured = capsys.readouterr()
    assert "shell 历史" in captured.err
    assert PASSWORD not in captured.out + captured.err


@pytest.mark.parametrize("environ", [{}, {"OJ_ADMIN_PASSWORD": ""}])
def test_noninteractive_missing_password_is_error(environ):
    with pytest.raises(admin.CommandError) as error:
        admin.read_admin_password(environ, StringIO())
    assert error.value.exit_code == 2


def test_validation_preserves_password():
    data = admin.validate_admin_input("Admin_01", PASSWORD)
    assert data.username == "Admin_01"
    assert data.password == PASSWORD


@pytest.mark.parametrize(
    ("username", "password"),
    [("ab", PASSWORD), ("用户名字", PASSWORD), ("alice", "short"), ("alice", " " * 15)],
)
def test_invalid_input_has_fixed_safe_error(username, password):
    with pytest.raises(admin.CommandError) as error:
        admin.validate_admin_input(username, password)
    assert error.value.exit_code == 2
    assert str(error.value) == "用户名或密码不符合注册规则"


@pytest.mark.parametrize("key", ["uk_users_username", "users.uk_users_username"])
def test_username_constraint_is_recognized(key):
    assert admin.is_username_conflict(integrity_error(key=key))


@pytest.mark.parametrize(
    ("code", "message"),
    [
        (1062, "private-value for key 'PRIMARY'"),
        (1062, "private-value for key 'other_unique'"),
        (1062, "private-value for key 'other.uk_users_username'"),
        (1062, "private-value uk_users_username"),
        (1062, "private-value for key 'users.uk_users_username_extra'"),
        (1062, "private-value for key 'users.uk_users_username' trailing"),
        (1452, "private-value for key 'users.uk_users_username'"),
        (1062, None),
    ],
)
def test_other_constraints_and_unknown_formats_are_not_username_conflicts(
    code, message
):
    error = IntegrityError("INSERT", {}, DriverIntegrityError(code, message))
    assert not admin.is_username_conflict(error)


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("method", "role"), [("create", "USER"), ("create_admin", "ADMIN")]
)
async def test_repository_paths_keep_fixed_roles_and_shared_active_status(method, role):
    session = Session()
    user = await getattr(UserRepository(session), method)("alice", "unit-encoded-hash")
    assert (user.role, user.status) == (role, "ACTIVE")
    assert user.username == "alice" and user.password_hash == "unit-encoded-hash"
    assert session.events == ["add", "flush", "refresh"]
    assert session.committed == []  # 仓储没有提交权限。


@pytest.mark.anyio
async def test_admin_hashes_before_transaction_and_commits(monkeypatch):
    session = Session()
    fake_hash(monkeypatch, session)
    data = RegisterRequest(username="alice", password=PASSWORD)
    assert await admin.create_admin(session, data, object()) == 7
    assert session.events == ["hash", "begin", "add", "flush", "refresh", "commit"]
    assert len(session.committed) == 1
    assert (session.committed[0].role, session.committed[0].status) == (
        "ADMIN",
        "ACTIVE",
    )


@pytest.mark.anyio
@pytest.mark.parametrize("stage", ["flush", "refresh", "commit"])
async def test_write_failures_rollback_and_never_report_success(monkeypatch, stage):
    session = Session(stage)
    fake_hash(monkeypatch, session)
    with pytest.raises(RuntimeError, match="private-driver-marker"):
        await admin.create_admin(
            session, RegisterRequest(username="alice", password=PASSWORD), object()
        )
    assert session.events[-1] == "rollback"
    assert not session.pending and not session.committed


@pytest.mark.anyio
async def test_hash_failure_never_starts_transaction(monkeypatch):
    session = Session()
    monkeypatch.setattr(
        admin, "hash_password", AsyncMock(side_effect=RuntimeError("secret"))
    )
    with pytest.raises(RuntimeError):
        await admin.create_admin(
            session, RegisterRequest(username="alice", password=PASSWORD), object()
        )
    assert session.events == []


@pytest.mark.anyio
async def test_real_argon2_admin_password_is_usable_and_not_output(capsys, caplog):
    session = Session()
    ctx = await admin.build_password_context()
    await admin.create_admin(
        session, RegisterRequest(username="alice", password=PASSWORD), ctx
    )
    encoded = session.committed[0].password_hash
    assert encoded.startswith("$argon2id$")
    assert ctx.hasher.verify(encoded, PASSWORD)
    captured = capsys.readouterr()
    assert PASSWORD not in captured.out + captured.err + caplog.text
    assert encoded not in captured.out + captured.err + caplog.text


@pytest.mark.parametrize("stage", ["flush", "commit"])
@pytest.mark.parametrize(
    ("key", "exit_code"), [("users.uk_users_username", 3), ("other_unique", 70)]
)
def test_conflict_exit_codes_and_redaction(
    monkeypatch, capsys, caplog, stage, key, exit_code
):
    session = Session(stage, integrity_error(key=key))
    fake_hash(monkeypatch, session)
    monkeypatch.setattr(admin, "read_admin_password", lambda env: PASSWORD)
    monkeypatch.setattr(admin, "database_url", lambda env: SecretStr(URL))

    async def run(data, url):
        return await admin.create_admin(session, data, object())

    monkeypatch.setattr(admin, "run", run)
    assert admin.main(["--username", "alice"]) == exit_code
    assert session.events[-1] == "rollback"
    output = capsys.readouterr()
    combined = output.out + output.err + caplog.text
    assert output.out == ""
    for private in [PASSWORD, URL, "private-value", "unit-encoded-hash"]:
        assert private not in combined


def test_help_does_not_read_config_password_or_connect(monkeypatch, capsys):
    def forbidden(*args, **kwargs):
        pytest.fail("--help 不得读取输入/配置或构造数据库资源")

    for name in ["read_admin_password", "database_url", "run", "create_async_engine"]:
        monkeypatch.setattr(admin, name, forbidden)
    with pytest.raises(SystemExit) as result:
        admin.main(["--help"])
    assert result.value.code == 0
    assert "--username" in capsys.readouterr().out


@pytest.mark.parametrize(
    "argv", [[], ["--password", PASSWORD], ["--unknown", PASSWORD]]
)
def test_argument_errors_do_not_echo_argv(argv, capsys):
    assert admin.main(argv) == 2
    captured = capsys.readouterr()
    assert PASSWORD not in captured.out + captured.err


@pytest.mark.parametrize(
    "value", [None, "private-invalid-dsn", "mysql+pymysql://u:p@host/db"]
)
def test_database_config_errors_are_safe(value):
    with pytest.raises(admin.CommandError) as result:
        admin.database_url({} if value is None else {"DATABASE_URL": value})
    assert result.value.exit_code == 2
    assert str(result.value) == "DATABASE_URL 缺失或格式不合法"


def test_database_config_needs_no_redis_or_jwt():
    assert admin.database_url({"DATABASE_URL": URL}).get_secret_value() == URL


@pytest.mark.anyio
@pytest.mark.parametrize("fail", [False, True])
async def test_run_uses_utc_and_always_releases_engine(monkeypatch, fail):
    events = []
    engine = SimpleNamespace(
        dispose=AsyncMock(side_effect=lambda: events.append("dispose"))
    )
    options = {}

    def create_engine(url, **kwargs):
        assert url == URL
        options.update(kwargs)
        return engine

    @asynccontextmanager
    async def session_context():
        events.append("open")
        try:
            yield object()
        finally:
            events.append("close")

    def session_factory(actual_engine, **kwargs):
        assert actual_engine is engine and kwargs == {"expire_on_commit": False}
        return session_context

    async def create(session, data, ctx):
        if fail:
            raise OperationalError("INSERT", {}, Exception("private-db-secret"))
        return 7

    monkeypatch.setattr(
        admin, "build_password_context", AsyncMock(return_value=object())
    )
    monkeypatch.setattr(admin, "create_async_engine", create_engine)
    monkeypatch.setattr(admin, "async_sessionmaker", session_factory)
    monkeypatch.setattr(admin, "create_admin", create)
    data = RegisterRequest(username="alice", password=PASSWORD)
    if fail:
        with pytest.raises(OperationalError):
            await admin.run(data, SecretStr(URL))
    else:
        assert await admin.run(data, SecretStr(URL)) == 7
    assert events == ["open", "close", "dispose"]
    assert options["hide_parameters"] is True and options["echo"] is False
    assert options["poolclass"] is admin.NullPool
    assert options["connect_args"] == {
        "init_command": "SET time_zone = '+00:00'",
        "connect_timeout": 5,
    }


@pytest.mark.parametrize(
    ("failure", "code"), [(RuntimeError(PASSWORD), 70), (KeyboardInterrupt(), 130)]
)
def test_top_level_failure_and_interrupt_are_redacted(
    monkeypatch, capsys, failure, code
):
    monkeypatch.setattr(admin, "read_admin_password", lambda env: PASSWORD)
    monkeypatch.setattr(admin, "database_url", lambda env: SecretStr(URL))
    monkeypatch.setattr(admin, "run", AsyncMock(side_effect=failure))
    assert admin.main(["--username", "alice"]) == code
    captured = capsys.readouterr()
    assert not captured.out and PASSWORD not in captured.err


def test_success_only_after_run_completes(monkeypatch, capsys):
    monkeypatch.setattr(admin, "read_admin_password", lambda env: PASSWORD)
    monkeypatch.setattr(admin, "database_url", lambda env: SecretStr(URL))
    monkeypatch.setattr(admin, "run", AsyncMock(return_value=7))
    assert admin.main(["--username", "alice"]) == 0
    assert "id=7" in capsys.readouterr().out
