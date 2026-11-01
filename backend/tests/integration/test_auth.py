"""真实 MySQL/Redis 认证场景；只由受控入口及双 owner 门禁放行。

HTTP 使用 ASGITransport 经过真实路由、lifespan、服务与驱动，不启动监听端口。
故障注入只改变测试中的时序/异常点；数据库事务、池及 Redis Lua 均真实执行。
"""

import asyncio
import uuid
from contextlib import asynccontextmanager

import httpx2
import pytest
from fastapi import Request
from fastapi.security import HTTPAuthorizationCredentials
from sqlalchemy import delete, func, select, text, update

from app.api.deps import get_current_user, require_admin
from app.core.http import AppError
from app.main import create_app
from app.models.user import User
from app.repositories.user import UserRepository

PASSWORD = "integration-only-password-42"


def username():
    return "u_" + uuid.uuid4().hex[:16]


@asynccontextmanager
async def live_application(settings, case):
    # 所有子用例键仍位于本轮完整 run_id 下；不删除其他用例或开发前缀。
    configured = settings.model_copy(
        update={"rate_limit_key_prefix": settings.rate_limit_key_prefix + ":" + case}
    )
    app = create_app(configured)
    async with app.router.lifespan_context(app):
        transport = httpx2.ASGITransport(app=app, raise_app_exceptions=False)
        async with httpx2.AsyncClient(
            transport=transport, base_url="http://auth-check"
        ) as client:
            yield app, client


async def register(client, name):
    return await client.post(
        "/api/v1/auth/register", json={"username": name, "password": PASSWORD}
    )


async def login(client, name):
    response = await client.post(
        "/api/v1/auth/login", json={"username": name, "password": PASSWORD}
    )
    assert response.status_code == 200
    return {"Authorization": "Bearer " + response.json()["access_token"]}


async def count_user(app, name):
    async with app.state.session_factory() as session:
        return await session.scalar(
            select(func.count()).select_from(User).where(User.username == name)
        )


def test_real_register_login_me_and_persisted_hash(auth_integration_settings):
    async def scenario():
        async with live_application(auth_integration_settings, "roundtrip") as (
            app,
            client,
        ):
            name = username()
            response = await register(client, name)
            assert response.status_code == 201
            assert "password_hash" not in response.json()
            headers = await login(client, name)
            me = await client.get("/api/v1/auth/me", headers=headers)
            assert me.status_code == 200
            assert me.json()["username"] == name
            async with app.state.session_factory() as session:
                encoded = await session.scalar(
                    select(User.password_hash).where(User.username == name)
                )
                assert encoded.startswith("$argon2id$") and encoded != PASSWORD
            assert await count_user(app, name) == 1

    asyncio.run(scenario())


def test_real_case_collision_under_concurrent_requests(
    auth_integration_settings, monkeypatch
):
    async def scenario():
        async with live_application(auth_integration_settings, "collision") as (
            app,
            client,
        ):
            name = username()
            entered = 0
            both = asyncio.Event()
            original = UserRepository.create

            async def rendezvous(repository, name, encoded):
                nonlocal entered
                entered += 1
                if entered == 2:
                    both.set()
                await asyncio.wait_for(both.wait(), 5)
                return await original(repository, name, encoded)

            # 两个真实 HTTP 请求都抵达写入点再放行，唯一约束决定胜者。
            monkeypatch.setattr(UserRepository, "create", rendezvous)
            responses = await asyncio.gather(
                register(client, name), register(client, name.upper())
            )
            assert sorted(r.status_code for r in responses) == [201, 409]
            assert entered == 2 and await count_user(app, name) == 1
            monkeypatch.setattr(UserRepository, "create", original)
            assert (await register(client, name.upper())).status_code == 409

    asyncio.run(scenario())


def test_real_transaction_rolls_back_after_insert(
    auth_integration_settings, monkeypatch
):
    async def scenario():
        async with live_application(auth_integration_settings, "rollback") as (
            app,
            client,
        ):
            name = username()
            original = UserRepository.create
            flushed = []

            async def fail_after_flush(repository, name, encoded):
                user = await original(repository, name, encoded)
                flushed.append(user.id)
                raise RuntimeError("injected-after-real-insert")

            monkeypatch.setattr(UserRepository, "create", fail_after_flush)
            assert (await register(client, name)).status_code == 500
            assert len(flushed) == 1  # INSERT/refresh 已成功，失败发生于 commit 之前。
            assert await count_user(app, name) == 0
            monkeypatch.setattr(UserRepository, "create", original)
            assert (await register(client, name)).status_code == 201
            assert await count_user(app, name) == 1

    asyncio.run(scenario())


def test_real_same_token_observes_role_status_and_deletion(auth_integration_settings):
    async def scenario():
        async with live_application(auth_integration_settings, "identity") as (
            app,
            client,
        ):
            name = username()
            assert (await register(client, name)).status_code == 201
            headers = await login(client, name)

            async def change(**values):
                async with app.state.session_factory.begin() as session:
                    await session.execute(
                        update(User).where(User.username == name).values(**values)
                    )

            async def check_admin():
                # 无生产测试路由：直接调用现有依赖，仍经真实 JWT 校验和新会话查库。
                async with app.state.session_factory() as session:
                    credentials = HTTPAuthorizationCredentials(
                        scheme="Bearer", credentials=headers["Authorization"][7:]
                    )
                    user = await get_current_user(
                        Request({"type": "http", "app": app}), session, credentials
                    )
                    return await require_admin(user)

            await change(role="ADMIN")
            assert (await check_admin()).role == "ADMIN"
            await change(role="USER")
            me = await client.get("/api/v1/auth/me", headers=headers)
            assert me.status_code == 200 and me.json()["role"] == "USER"
            with pytest.raises(AppError) as error:
                await check_admin()
            assert error.value.status == 403
            await change(status="DISABLED")
            assert (
                await client.get("/api/v1/auth/me", headers=headers)
            ).status_code == 403
            await change(status="ACTIVE")
            assert (
                await client.get("/api/v1/auth/me", headers=headers)
            ).status_code == 200
            async with app.state.session_factory.begin() as session:
                await session.execute(delete(User).where(User.username == name))
            assert (
                await client.get("/api/v1/auth/me", headers=headers)
            ).status_code == 401

    asyncio.run(scenario())


def test_real_lua_concurrency_ttl_repair_and_expiry(auth_integration_settings):
    async def scenario():
        async with live_application(auth_integration_settings, "lua") as (app, _):
            limiter = app.state.rate_limiter
            key = limiter.prefix + ":atomic"
            values = await asyncio.gather(
                *(limiter._evaluate(key, "consume", 1) for _ in range(32))
            )
            assert sorted(count for count, _ in values) == list(range(1, 33))
            assert 0 < await limiter.redis.pttl(key) <= 1000
            await limiter.redis.set(
                key, "5"
            )  # 本轮测试键故意去掉 TTL，验证生产 Lua 修复。
            assert await limiter.redis.pttl(key) == -1
            count, ttl = await limiter._evaluate(key, "read", 1)
            assert count == 5 and 0 < ttl <= 1000
            deadline = asyncio.get_running_loop().time() + 3
            while await limiter.redis.exists(key):
                assert asyncio.get_running_loop().time() < deadline
                await asyncio.sleep(0.05)
            assert await limiter.redis.pttl(key) == -2

    asyncio.run(scenario())


def test_real_http_registration_and_login_limits(auth_integration_settings):
    async def scenario():
        async with live_application(auth_integration_settings, "limits") as (
            app,
            client,
        ):
            names = [username() for _ in range(6)]
            for name in names[:5]:
                assert (await register(client, name)).status_code == 201
            limited = await register(client, names[5])
            assert (
                limited.status_code == 429 and int(limited.headers["Retry-After"]) > 0
            )
            assert await count_user(app, names[5]) == 0
            for _ in range(5):
                response = await client.post(
                    "/api/v1/auth/login",
                    json={"username": names[0], "password": "incorrect"},
                )
                assert response.status_code == 401
            response = await client.post(
                "/api/v1/auth/login",
                json={"username": names[0].upper(), "password": PASSWORD},
            )
            assert (
                response.status_code == 429 and int(response.headers["Retry-After"]) > 0
            )

    asyncio.run(scenario())


def test_real_application_pool_queue_timeout_cancel_and_recovery(
    auth_integration_settings, monkeypatch
):
    from app.core import db

    original = db.create_async_engine

    def small_pool(*args, **kwargs):
        return original(*args, **kwargs, pool_size=1, max_overflow=0, pool_timeout=0.25)

    # 只缩小真实池容量和超时以便确定性制造耗尽，保留生产会话工厂及依赖处理。
    monkeypatch.setattr(db, "create_async_engine", small_pool)

    async def scenario():
        async with live_application(auth_integration_settings, "pool") as (app, client):
            name = username()
            assert (await register(client, name)).status_code == 201
            headers = await login(client, name)
            engine = app.state.session_factory.kw["bind"]
            held = await engine.connect()
            try:
                waiting = asyncio.create_task(
                    client.get("/api/v1/auth/me", headers=headers)
                )
                await asyncio.sleep(0.03)
                assert not waiting.done()
                assert (await waiting).status_code == 503
                waiting = asyncio.create_task(
                    client.get("/api/v1/auth/me", headers=headers)
                )
                await asyncio.sleep(0.03)
                assert not waiting.done()
                waiting.cancel()
                with pytest.raises(asyncio.CancelledError):
                    await waiting
                waiting = asyncio.create_task(
                    client.get("/api/v1/auth/me", headers=headers)
                )
                await asyncio.sleep(0.03)
                assert not waiting.done()
            finally:
                await held.close()
            assert (await waiting).status_code == 200
            assert (
                await client.get("/api/v1/auth/me", headers=headers)
            ).status_code == 200
            assert engine.pool.checkedout() == 0

    asyncio.run(scenario())


def test_real_application_session_uses_explicit_utc(auth_integration_settings):
    """核对生产 lifespan 创建的应用连接，不能用管理连接或单独驱动代替。"""

    async def scenario():
        async with live_application(auth_integration_settings, "utc") as (app, _):
            async with app.state.session_factory() as session:
                row = (
                    await session.execute(
                        text(
                            "SELECT @@session.time_zone, "
                            "TIMESTAMPDIFF(SECOND, UTC_TIMESTAMP(), NOW())"
                        )
                    )
                ).one()
                assert row[0] == "+00:00"
                assert row[1] == 0

    asyncio.run(scenario())
