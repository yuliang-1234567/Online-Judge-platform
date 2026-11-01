from unittest.mock import AsyncMock

import pytest
from redis.exceptions import ConnectionError

from app.core import rate_limit
from app.core.http import AppError
from app.core.rate_limit import RATE_LIMIT_SCRIPT, AuthRateLimiter


@pytest.fixture
def anyio_backend():
    return "asyncio"


def limiter(result=(1, 60000)):
    redis = AsyncMock()
    redis.eval.return_value = result
    return AuthRateLimiter(redis, "oj:ratelimit:auth-test:offline"), redis


@pytest.mark.anyio
async def test_registration_uses_one_eval_and_sixth_attempt_is_429():
    subject, redis = limiter((6, 3210))
    with pytest.raises(AppError) as error:
        await subject.check_registration("127.0.0.1")
    assert (error.value.status, error.value.code, error.value.retry_after) == (
        429,
        "RATE_LIMITED",
        4,
    )
    args = redis.eval.call_args.args
    assert args[0] == RATE_LIMIT_SCRIPT
    assert args[1] == 1
    assert args[2].startswith("oj:ratelimit:auth-test:offline:register:")
    assert args[3:] == ("consume", 3600000)
    redis.eval.assert_awaited_once()


@pytest.mark.anyio
async def test_login_reads_failures_then_records_on_same_normalized_key():
    subject, redis = limiter((4, 10000))
    await subject.check_login("::1", "Alice")
    await subject.record_login_failure("0:0:0:0:0:0:0:1", "ALICE")
    check, record = [call.args for call in redis.eval.await_args_list]
    assert check[2] == record[2]
    assert check[3:] == ("read", 60000)
    assert record[3:] == ("consume", 60000)
    assert "Alice" not in check[2]


@pytest.mark.anyio
async def test_five_failed_logins_block_next_hash_attempt():
    subject, _ = limiter((5, 59999))
    with pytest.raises(AppError) as error:
        await subject.check_login("127.0.0.1", "alice")
    assert error.value.status == 429
    assert error.value.retry_after == 60


@pytest.mark.anyio
@pytest.mark.parametrize("username", ["中文名", "a", "a" * 33, "alice\n", " alice"])
async def test_invalid_username_cannot_create_variant_limiter_keys(username):
    subject, redis = limiter()
    with pytest.raises(AppError) as error:
        await subject.check_login("127.0.0.1", username)
    assert error.value.status == 422
    redis.eval.assert_not_called()


@pytest.mark.anyio
async def test_registration_fails_closed_but_login_fails_open_without_leaks(
    caplog, monkeypatch
):
    # 既有 Alembic 离线测试会重配全局日志；恢复本测试的捕获入口而非放宽断言。
    monkeypatch.setattr(rate_limit.logger, "disabled", False)
    caplog.set_level("WARNING", logger=rate_limit.logger.name)
    subject, redis = limiter()
    redis.eval.side_effect = ConnectionError("redis-password-secret-marker")
    with pytest.raises(AppError) as error:
        await subject.check_registration("127.0.0.1")
    assert (error.value.status, error.value.code) == (503, "SERVICE_UNAVAILABLE")
    await subject.check_login("127.0.0.1", "alice")
    await subject.record_login_failure("127.0.0.1", "alice")
    assert "login_rate_limit_unavailable" in caplog.text
    assert "redis-password-secret-marker" not in caplog.text


def test_distinct_usernames_do_not_claim_an_ip_wide_quota():
    subject, _ = limiter()
    assert subject._key("login", "127.0.0.1", "alice") != subject._key(
        "login", "127.0.0.1", "bobby"
    )
    # 此处只检验客户端协议和决策；Lua 在真实 Redis 的执行与并发原子性留到 07.5b。
