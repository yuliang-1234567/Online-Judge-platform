import asyncio
import threading
import time
from types import SimpleNamespace

import anyio
import jwt
import pytest
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

from app.core import security
from app.core.config import Settings
from app.core.security import (
    MAX_USER_ID,
    CorruptPasswordHash,
    HashCapacityExceeded,
    InvalidAccessToken,
    PasswordContext,
    build_password_context,
    create_access_token,
    decode_access_token,
    hash_password,
    verify_dummy_password,
    verify_password,
)


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture
def settings():
    return Settings(
        database_url="mysql+asyncmy://placeholder:placeholder@127.0.0.1:1/offline",
        redis_url="redis://127.0.0.1:1/4",
        jwt_secret="unit-only-signing-key-" + "x" * 48,
    )


@pytest.mark.anyio
async def test_real_argon2_salts_and_password_preservation():
    ctx = await build_password_context()
    password = "  Unicode密码与空格必须原样保留  "
    first = await hash_password(password, ctx=ctx)
    second = await hash_password(password, ctx=ctx)
    assert first != second
    assert first.startswith("$argon2id$")
    assert await verify_password(password, first, ctx=ctx)
    assert not await verify_password(password.strip(), first, ctx=ctx)
    assert ctx.limiter.borrowed_tokens == 0


@pytest.mark.anyio
async def test_hash_exceptions_are_not_all_wrong_passwords():
    ctx = await build_password_context()
    with pytest.raises(CorruptPasswordHash):
        await verify_password("password", "invalid-hash-secret", ctx=ctx)
    assert ctx.limiter.borrowed_tokens == 0

    def unknown_failure(*args):
        raise VerificationError("internal-hash-marker")

    ctx.hasher = SimpleNamespace(verify=unknown_failure)
    with pytest.raises(VerificationError):
        await verify_password("password", "encoded", ctx=ctx)


@pytest.mark.anyio
async def test_dummy_verification_uses_same_pool_and_never_returns_identity():
    calls = []
    main_thread = threading.get_ident()
    ctx = PasswordContext(None, anyio.CapacityLimiter(2), "dummy-encoded")

    def verify(encoded, password):
        calls.append(
            (encoded, password, ctx.limiter.borrowed_tokens, threading.get_ident())
        )
        return True

    ctx.hasher = SimpleNamespace(verify=verify)
    assert await verify_dummy_password("candidate", ctx=ctx) is None
    assert calls[0][:3] == ("dummy-encoded", "candidate", 1)
    assert calls[0][3] != main_thread
    assert ctx.limiter.borrowed_tokens == 0


@pytest.mark.anyio
@pytest.mark.parametrize("failure", [InvalidHashError, VerifyMismatchError])
async def test_admission_returns_to_zero_after_hash_exception(failure):
    ctx = PasswordContext(None, anyio.CapacityLimiter(2), "dummy")

    def verify(*args):
        assert ctx.limiter.borrowed_tokens == 1
        raise failure("sensitive-marker")

    ctx.hasher = SimpleNamespace(verify=verify)
    if failure is InvalidHashError:
        with pytest.raises(CorruptPasswordHash):
            await verify_password("password", "encoded", ctx=ctx)
    else:
        assert not await verify_password("password", "encoded", ctx=ctx)
    assert ctx.limiter.borrowed_tokens == 0


@pytest.mark.anyio
@pytest.mark.parametrize("cancel_kind", ["task", "scope"])
async def test_cancel_keeps_slot_until_worker_really_stops(cancel_kind):
    started = threading.Event()
    release = threading.Event()
    finished = threading.Event()
    ctx = PasswordContext(None, anyio.CapacityLimiter(2), "dummy")

    def work(value):
        started.set()
        try:
            assert release.wait(5)
            return "encoded"
        finally:
            finished.set()

    ctx.hasher = SimpleNamespace(hash=work)
    scope = anyio.CancelScope()

    async def invoke():
        with scope:
            await hash_password("password", ctx=ctx)

    task = asyncio.create_task(invoke())
    try:
        with anyio.fail_after(5):
            while not started.is_set():
                await anyio.sleep(0.001)
        assert ctx.limiter.borrowed_tokens == 1
        if cancel_kind == "task":
            task.cancel()
        else:
            scope.cancel()
        await anyio.sleep(0)
        assert ctx.limiter.borrowed_tokens == 1
        assert not finished.is_set()
    finally:
        release.set()
    if cancel_kind == "task":
        with pytest.raises(asyncio.CancelledError):
            await task
    else:
        await task
    assert finished.is_set()
    assert ctx.limiter.borrowed_tokens == 0


@pytest.mark.anyio
async def test_real_and_dummy_share_two_slots_and_third_is_rejected():
    entered = []
    release = threading.Event()
    ctx = PasswordContext(None, anyio.CapacityLimiter(2), "dummy")

    def verify(*args):
        entered.append(args)
        assert release.wait(5)
        return False

    ctx.hasher = SimpleNamespace(verify=verify)
    first = asyncio.create_task(verify_password("p", "real", ctx=ctx))
    second = asyncio.create_task(verify_dummy_password("p", ctx=ctx))
    try:
        with anyio.fail_after(5):
            while len(entered) != 2:
                await anyio.sleep(0.001)
        assert ctx.limiter.borrowed_tokens == 2
        with pytest.raises(HashCapacityExceeded):
            await verify_password("p", "third", ctx=ctx)
    finally:
        release.set()
        await asyncio.gather(first, second)
    assert ctx.limiter.borrowed_tokens == 0


def test_jwt_roundtrip_payload_and_unsigned_bigint_limit(settings):
    token = create_access_token(MAX_USER_ID, settings=settings)
    payload = jwt.decode(
        token, settings.jwt_secret.get_secret_value(), algorithms=["HS256"]
    )
    assert set(payload) == {"sub", "iat", "exp"}
    claims = decode_access_token(token, settings=settings)
    assert claims.user_id == MAX_USER_ID
    assert claims.expires_at - claims.issued_at == 3600


@pytest.mark.parametrize(
    "subject",
    ["0", "01", "-1", "+1", "1\n", " 1", "", "1" * 21, str(MAX_USER_ID + 1), 1, True],
)
def test_sub_requires_fullmatch_and_preconversion_length_bound(settings, subject):
    now = int(time.time())
    token = jwt.encode(
        {"sub": subject, "iat": now, "exp": now + 100},
        settings.jwt_secret.get_secret_value(),
        algorithm="HS256",
    )
    with pytest.raises(InvalidAccessToken):
        decode_access_token(token, settings=settings)


@pytest.mark.parametrize("field", ["iat", "exp"])
@pytest.mark.parametrize("kind", ["bool", "float", "str"])
def test_original_claims_must_be_exact_int(settings, monkeypatch, field, kind):
    now = int(time.time())
    payload = {"sub": "1", "iat": now, "exp": now + 100}
    value = payload[field]
    payload[field] = {"bool": True, "float": float(value), "str": str(value)}[kind]
    # 直接保留解码后的原始值，证明本项目的检查没有依赖 PyJWT 的 int() 强转。
    monkeypatch.setattr(security.jwt, "decode", lambda *args, **kwargs: payload)
    with pytest.raises(InvalidAccessToken):
        decode_access_token("opaque", settings=settings)


@pytest.mark.parametrize("field", ["iat", "exp"])
def test_real_pyjwt_float_coercion_does_not_bypass_our_validation(settings, field):
    now = int(time.time())
    payload = {"sub": "1", "iat": now - 1, "exp": now + 100}
    payload[field] = float(payload[field])
    key = settings.jwt_secret.get_secret_value()
    token = jwt.encode(payload, key, algorithm="HS256")
    assert type(jwt.decode(token, key, algorithms=["HS256"])[field]) is float
    with pytest.raises(InvalidAccessToken):
        decode_access_token(token, settings=settings)


@pytest.mark.parametrize(
    "case",
    [
        "expired",
        "future_iat",
        "signature",
        "algorithm",
        "missing_iat",
        "missing_exp",
        "order",
    ],
)
def test_invalid_jwt_is_rejected(settings, case):
    now = int(time.time())
    payload = {"sub": "1", "iat": now, "exp": now + 100}
    key = settings.jwt_secret.get_secret_value()
    algorithm = "HS256"
    if case == "expired":
        payload.update(iat=now - 100, exp=now - 1)
    elif case == "future_iat":
        payload["iat"] = now + 10
    elif case == "signature":
        key = "another-unit-key-32-bytes-minimum"
    elif case == "algorithm":
        algorithm = "HS384"
    elif case.startswith("missing_"):
        del payload[case.removeprefix("missing_")]
    else:
        payload["exp"] = now
    token = jwt.encode(payload, key, algorithm=algorithm)
    with pytest.raises(InvalidAccessToken):
        decode_access_token(token, settings=settings)


@pytest.mark.anyio
async def test_password_context_is_per_application_instance():
    first, second = await build_password_context(), await build_password_context()
    assert first.limiter is not second.limiter
    assert first.dummy_hash != second.dummy_hash
    assert first.limiter.total_tokens == second.limiter.total_tokens == 2
    assert isinstance(first.hasher, PasswordHasher)


@pytest.mark.parametrize("value", [0, -1, True, 1.5, MAX_USER_ID + 1])
def test_signing_rejects_invalid_user_identifiers(settings, value):
    with pytest.raises(ValueError):
        create_access_token(value, settings=settings)
