from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy.exc import IntegrityError, OperationalError

from app.core.config import Settings
from app.core.http import AppError
from app.schemas.auth import LoginRequest, RegisterRequest
from app.services import auth
from app.services.auth import AuthService


@pytest.fixture
def anyio_backend():
    return "asyncio"


class Session:
    def __init__(self, events):
        self.events = events
        self.commit_error = None

    @asynccontextmanager
    async def begin(self):
        self.events.append("begin")
        try:
            yield
            if self.commit_error:
                raise self.commit_error
            self.events.append("commit")
        except Exception:
            self.events.append("rollback")
            raise


@pytest.fixture
def subject(monkeypatch):
    events = []
    session = Session(events)
    repository = AsyncMock()
    limiter = AsyncMock()
    settings = Settings(
        database_url="mysql+asyncmy://placeholder:placeholder@127.0.0.1:1/offline",
        redis_url="redis://127.0.0.1:1/4",
        jwt_secret="service-only-key-with-more-than-32-bytes",
    )

    async def hash_password(*args, **kwargs):
        events.append("hash")
        return "encoded"

    monkeypatch.setattr(auth, "hash_password", hash_password)
    return AuthService(session, repository, object(), limiter, settings), events


@pytest.mark.anyio
async def test_register_hashes_before_transaction_and_commits(subject):
    service, events = subject
    service.users.create.return_value = "user"
    result = await service.register(
        RegisterRequest(username="alice", password="password-15-characters"),
        "127.0.0.1",
    )
    assert result == "user"
    assert events == ["hash", "begin", "commit"]
    service.users.create.assert_awaited_once_with("alice", "encoded")
    service.limiter.check_registration.assert_awaited_once()


@pytest.mark.anyio
@pytest.mark.parametrize("failure_stage", ["flush", "commit"])
async def test_username_conflict_rolls_back_and_maps_409(subject, failure_stage):
    service, events = subject
    conflict = IntegrityError(
        "INSERT",
        {},
        Exception(1062, "Duplicate entry for key 'users.uk_users_username'"),
    )
    if failure_stage == "flush":
        service.users.create.side_effect = conflict
    else:
        service.session.commit_error = conflict
    with pytest.raises(AppError) as error:
        await service.register(
            RegisterRequest(username="alice", password="password-15-characters"),
            "127.0.0.1",
        )
    assert (error.value.status, error.value.code) == (409, "CONFLICT")
    assert events == ["hash", "begin", "rollback"]


@pytest.mark.anyio
async def test_other_integrity_error_is_not_mislabeled_username_conflict(subject):
    service, events = subject
    service.users.create.side_effect = IntegrityError(
        "INSERT", {}, Exception(1062, "Duplicate entry for key 'other_key'")
    )
    with pytest.raises(IntegrityError):
        await service.register(
            RegisterRequest(username="alice", password="password-15-characters"),
            "127.0.0.1",
        )
    assert events[-1] == "rollback"


@pytest.mark.anyio
async def test_database_unavailable_maps_503(subject):
    service, _ = subject
    service.users.by_username.side_effect = OperationalError(
        "SELECT", {}, Exception("private-password")
    )
    with pytest.raises(AppError) as error:
        await service.login(
            LoginRequest(username="alice", password="wrong"), "127.0.0.1"
        )
    assert (error.value.status, error.value.code) == (503, "SERVICE_UNAVAILABLE")
    assert "private-password" not in str(error.value)


@pytest.mark.anyio
async def test_missing_user_and_wrong_password_have_identical_401(subject, monkeypatch):
    service, events = subject
    real = AsyncMock(return_value=False)
    dummy = AsyncMock()
    monkeypatch.setattr(auth, "verify_password", real)
    monkeypatch.setattr(auth, "verify_dummy_password", dummy)
    data = LoginRequest(username="alice", password="wrong")
    failures = []
    for user in [None, SimpleNamespace(password_hash="encoded")]:
        service.users.by_username.return_value = user
        with pytest.raises(AppError) as error:
            await service.login(data, "127.0.0.1")
        failures.append((error.value.status, error.value.code, error.value.message))
    assert failures == [(401, "UNAUTHENTICATED", "用户名或密码错误")] * 2
    dummy.assert_awaited_once_with("wrong", ctx=service.passwords)
    real.assert_awaited_once_with("wrong", "encoded", ctx=service.passwords)
    assert service.limiter.record_login_failure.await_count == 2
    assert events == ["begin", "commit", "begin", "commit"]


@pytest.mark.anyio
async def test_disabled_account_requires_correct_password_before_403(
    subject, monkeypatch
):
    service, _ = subject
    service.users.by_username.return_value = SimpleNamespace(
        password_hash="encoded", status="DISABLED"
    )
    monkeypatch.setattr(auth, "verify_password", AsyncMock(return_value=True))
    with pytest.raises(AppError) as error:
        await service.login(
            LoginRequest(username="alice", password="right"), "127.0.0.1"
        )
    assert error.value.status == 403
    service.limiter.record_login_failure.assert_not_called()


@pytest.mark.anyio
async def test_rate_limit_rejection_prevents_lookup_and_hash(subject, monkeypatch):
    service, _ = subject
    service.limiter.check_login.side_effect = AppError(
        429, "RATE_LIMITED", "limited", retry_after=1
    )
    verify = AsyncMock()
    monkeypatch.setattr(auth, "verify_password", verify)
    with pytest.raises(AppError):
        await service.login(
            LoginRequest(username="alice", password="wrong"), "127.0.0.1"
        )
    service.users.by_username.assert_not_called()
    verify.assert_not_called()
