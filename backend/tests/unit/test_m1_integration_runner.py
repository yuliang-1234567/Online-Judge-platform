"""离线验证 suite 边界与真实用例的可收集性；禁止外连，不执行集成用例。"""

import contextlib
import json
import socket
import subprocess
import sys
import uuid
from types import SimpleNamespace

import pytest
from sqlalchemy.engine import URL

from tools import auth_integration as runner


@pytest.fixture(autouse=True)
def forbid_network(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("suite 离线回归禁止外连")

    monkeypatch.setattr(socket.socket, "connect", forbidden)
    monkeypatch.setattr(socket, "getaddrinfo", forbidden)


def environment():
    run_id = uuid.uuid4().hex
    url = URL.create(
        "mysql+asyncmy",
        username=runner.account_name(run_id, "a"),
        password="offline-only",
        host="127.0.0.1",
        port=13306,
        database=runner.DATABASE,
    ).render_as_string(hide_password=False)
    return runner.build_child_environment(
        run_id,
        url,
        "redis://:offline-only@127.0.0.1:16379/4",
        "offline-jwt-with-at-least-thirty-two-bytes",
    )


@pytest.mark.parametrize(
    "suite,tables",
    [
        ("auth", ("users",)),
        ("m1-access", ("users", "audit_logs")),
        (
            "m1-problems",
            (
                "users",
                "audit_logs",
                "problems",
                "tags",
                "problem_tags",
                "test_cases",
                "submissions",
                "submission_cases",
            ),
        ),
    ],
)
def test_suite_grants_only_its_tables_and_readonly_owner(suite, tables):
    calls = []
    db = SimpleNamespace(execute=lambda sql, params=(): calls.append((sql, params)))
    run_id = uuid.uuid4().hex
    runner.grant_application_account(db, run_id, suite=suite)
    account = runner.account_literal(run_id, "a")
    expected = []
    for table in tables:
        privileges = {
            "audit_logs": "SELECT, INSERT",
            "submissions": "SELECT, INSERT, UPDATE",
            "submission_cases": "SELECT, INSERT",
        }.get(table, "SELECT, INSERT, UPDATE, DELETE")
        expected.append(
            (f"GRANT {privileges} ON `oj_auth_check`.`{table}` TO {account}", ())
        )
    expected.append(
        (f"GRANT SELECT ON `oj_auth_check`.`__auth_check_owner` TO {account}", ())
    )
    assert calls == expected


def test_invalid_suite_fails_before_grant_or_child(monkeypatch):
    calls = []
    db = SimpleNamespace(execute=lambda *args: calls.append(args))
    with pytest.raises(runner.RunnerError) as error:
        runner.grant_application_account(db, uuid.uuid4().hex, suite="secret-marker")
    assert error.value.exit_code == 64 and "secret-marker" not in str(error.value)
    assert calls == []
    state = runner.RunState(uuid.uuid4().hex, suite="secret-marker")
    monkeypatch.setattr(
        runner.subprocess, "Popen", lambda *a, **kw: pytest.fail("child started")
    )
    with pytest.raises(runner.RunnerError):
        runner.ChildSupervisor(state).run_pytest({})


@pytest.mark.parametrize("suite", tuple(runner.SUITE_FILES))
def test_suite_pytest_selection_keeps_exact_child_environment(monkeypatch, suite):
    env = environment()
    state = runner.RunState(runner.validate_child_environment(env), suite=suite)
    observed = {}

    def start(argv, **options):
        observed.update(argv=argv, **options)
        return SimpleNamespace(
            returncode=0, communicate=lambda **kw: ("8 passed", None)
        )

    monkeypatch.setattr(runner.subprocess, "Popen", start)
    assert runner.ChildSupervisor(state).run_pytest(env) == 0
    assert observed["argv"][5] == runner.SUITE_FILES[suite]
    assert "tests/integration" not in observed["argv"]
    assert set(observed["env"]) == runner.CHILD_ENV_KEYS
    assert observed["start_new_session"] is True
    assert observed["stdin"] == subprocess.DEVNULL


@pytest.mark.parametrize("suite", tuple(runner.SUITE_FILES))
def test_suite_evidence_directory(suite):
    state = runner.RunState(uuid.uuid4().hex, suite=suite)
    directory = runner.evidence_directory(state)
    expected = "07.5b" if suite == "auth" else f"m1/{suite}"
    assert (
        directory == runner.ROOT / "local-reference/runtime" / expected / state.run_id
    )


@pytest.mark.parametrize(
    "argv,suite",
    [
        ([], "auth"),
        (["--suite", "auth"], "auth"),
        (["--suite", "m1-access"], "m1-access"),
        (["--suite", "m1-problems"], "m1-problems"),
    ],
)
def test_cli_selects_suite_without_running_services(monkeypatch, argv, suite):
    observed = []
    monkeypatch.setattr(
        runner, "signal_handlers", lambda state: contextlib.nullcontext()
    )
    monkeypatch.setattr(runner, "exclusive_lock", contextlib.nullcontext)
    monkeypatch.setattr(
        runner, "execute_locked", lambda state: observed.append(state.suite) or 0
    )
    assert runner.main(argv) == 0
    assert observed == [suite]


@pytest.mark.parametrize(
    "argv,code",
    [
        (["--help"], 0),
        (["--suite", "secret-marker"], 2),
        (["--suite"], 2),
        (["--unknown", "secret-marker"], 2),
    ],
)
def test_cli_help_and_invalid_arguments_never_read_credentials(
    monkeypatch, capsys, argv, code
):
    monkeypatch.setattr(
        runner, "load_management_credentials", lambda: pytest.fail("credentials read")
    )
    monkeypatch.setattr(runner, "exclusive_lock", lambda: pytest.fail("lock acquired"))
    with pytest.raises(SystemExit) as error:
        runner.main(argv)
    assert error.value.code == code
    captured = capsys.readouterr()
    assert "secret-marker" not in captured.err + captured.out


@pytest.mark.parametrize(
    "suite,count", [("auth", 8), ("m1-access", 7), ("m1-problems", 14)]
)
def test_suite_collects_expected_cases_offline(suite, count):
    # 只在本子进程用归属替身放行 collect-only。真实入口的服务端门禁原样保留。
    source = """
import os, socket, pytest, sys
from tools import auth_integration as runner
from sqlalchemy.engine import URL
import uuid
def forbidden(*args, **kwargs):
    raise AssertionError("collection attempted network")
sys.addaudithook(lambda event, args: forbidden() if event in
    {"socket.connect", "socket.getaddrinfo", "socket.sendto"} else None)
run_id = uuid.uuid4().hex
url = URL.create("mysql+asyncmy", username=runner.account_name(run_id, "a"),
    password="offline-only", host="127.0.0.1", port=13306, database=runner.DATABASE)
os.environ.update(runner.build_child_environment(run_id,
    url.render_as_string(hide_password=False),
    "redis://:offline-only@127.0.0.1:16379/4", "offline-key-at-least-thirty-two-bytes"))
runner.verify_server_ownership = lambda env: None
raise SystemExit(pytest.main(["--auth-integration", "--collect-only", "-q",
    runner.SUITE_FILES[sys.argv[1]], "-p", "no:cacheprovider"]))
"""
    result = subprocess.run(
        [sys.executable, "-B", "-c", source, suite],
        cwd=runner.BACKEND,
        env={"PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1", "PYTHONDONTWRITEBYTECODE": "1"},
        capture_output=True,
        text=True,
        timeout=20,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert f"{count} tests collected" in result.stdout


def test_default_collection_gate_still_excludes_integration():
    import importlib.util

    path = runner.BACKEND / "tests/conftest.py"
    spec = importlib.util.spec_from_file_location("_m1_default_gate", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    config = SimpleNamespace(getoption=lambda name: False)
    assert module.pytest_ignore_collect(
        runner.BACKEND / runner.SUITE_FILES["auth"], config
    )
    assert module.pytest_ignore_collect(
        runner.BACKEND / runner.SUITE_FILES["m1-access"], config
    )
    assert module.pytest_ignore_collect(
        runner.BACKEND / runner.SUITE_FILES["m1-problems"], config
    )


@pytest.mark.parametrize("suite", tuple(runner.SUITE_FILES))
def test_report_records_suite_when_preflight_fails(monkeypatch, tmp_path, suite):
    state = runner.RunState(uuid.uuid4().hex, suite=suite)
    monkeypatch.setattr(runner, "ROOT", tmp_path)
    monkeypatch.setattr(runner, "_container_snapshot", lambda: {})

    def fail_connection(*args, **kwargs):
        raise runner.RunnerError("offline preflight fault", 65)

    monkeypatch.setattr(runner, "PyMySqlExecutor", fail_connection)
    credentials = runner.ManagementCredentials(None, None)
    supervisor = SimpleNamespace(stop=lambda: None)
    assert runner.first_database_round(state, credentials, supervisor) == 65
    report = json.loads((runner.evidence_directory(state) / "report.json").read_text())
    assert report["suite"] == suite and report["run_id"] == state.run_id
    assert report["exit_code"] == 65
    assert report["development_before"] is None
    assert report["development_after"] is None
    assert report["containers_after"] is None
    assert report["development_unchanged"] is None


def test_admin_command_subprocess_has_only_application_credentials(monkeypatch):
    import asyncio
    import importlib.util

    from pydantic import SecretStr

    path = runner.BACKEND / "tests/integration/m1_support.py"
    spec = importlib.util.spec_from_file_location("_m1_support_offline", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    observed = {}

    async def communicate():
        return b"created", b""

    async def start(*argv, **options):
        observed.update(argv=argv, **options)
        return SimpleNamespace(returncode=0, communicate=communicate)

    monkeypatch.setenv("MYSQL_ROOT_PASSWORD", "management-marker")
    monkeypatch.setenv("DATABASE_URL_SYNC", "migration-marker")
    monkeypatch.setenv("REDIS_PASSWORD", "redis-management-marker")
    monkeypatch.setattr(asyncio, "create_subprocess_exec", start)
    live = module.M1Application(
        None, None, SimpleNamespace(database_url=SecretStr("application-only-dsn"))
    )
    assert asyncio.run(live.admin_command("offline_admin")) == 0
    assert set(observed["env"]) == {
        "DATABASE_URL",
        "OJ_ADMIN_PASSWORD",
        "PYTHONDONTWRITEBYTECODE",
    }
    assert observed["env"]["DATABASE_URL"] == "application-only-dsn"
    assert observed["env"]["OJ_ADMIN_PASSWORD"] == live.password
    assert live.password not in observed["argv"]
    assert "application-only-dsn" not in observed["argv"]
    assert not any("management-marker" in value for value in observed["env"].values())
    assert "start_new_session" not in observed  # 归属父 pytest 进程组。


@pytest.mark.parametrize(
    "versions,expected",
    [
        (None, None),
        ((), []),
        (("head-a", "head-b"), ["head-a", "head-b"]),
    ],
)
def test_development_snapshot_preserves_missing_empty_and_multiple_versions(
    versions, expected
):
    snapshot = runner.DevelopmentSnapshot(2, versions)
    assert runner.development_snapshot_values(snapshot) == {
        "table_count": 2,
        "alembic_version": expected,
    }
