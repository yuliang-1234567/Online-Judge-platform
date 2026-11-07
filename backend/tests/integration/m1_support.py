"""M1 实库用例共享装配。仅使用归属门禁传入的应用凭据及真实路由。"""

import asyncio
import secrets
import subprocess
import sys
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

import httpx2
from sqlalchemy import select, update

from app.main import create_app
from app.models.user import User


class M1Application:
    def __init__(self, app, client, settings):
        self.app, self.client, self.settings = app, client, settings
        self.password = secrets.token_urlsafe(24)
        self.user_ids = []

    async def admin_command(self, name):
        # 真实命令入口，密码/DSN 仅在环境内；后代继承 pytest 进程组供入口统一回收。
        process = await asyncio.create_subprocess_exec(
            sys.executable,
            "-B",
            "-m",
            "tools.create_admin",
            "--username",
            name,
            cwd=Path(__file__).resolve().parents[2],
            env={
                "DATABASE_URL": self.settings.database_url.get_secret_value(),
                "OJ_ADMIN_PASSWORD": self.password,
                "PYTHONDONTWRITEBYTECODE": "1",
            },
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        try:
            await asyncio.wait_for(process.communicate(), 15)
        finally:
            if process.returncode is None:
                process.kill()
                await process.wait()
        return process.returncode

    async def new_admin(self):
        name = "a_" + uuid.uuid4().hex[:20]
        assert await self.admin_command(name) == 0
        async with self.app.state.session_factory() as session:
            user_id = await session.scalar(select(User.id).where(User.username == name))
        assert user_id is not None
        self.user_ids.append(user_id)
        return user_id, name, await self.login(name)

    async def login(self, name):
        response = await self.client.post(
            "/api/v1/auth/login",
            json={"username": name, "password": self.password},
        )
        assert response.status_code == 200
        return {"Authorization": "Bearer " + response.json()["access_token"]}

    async def user_state(self, user_id):
        async with self.app.state.session_factory() as session:
            return (
                await session.execute(
                    select(User.role, User.status, User.password_hash).where(
                        User.id == user_id
                    )
                )
            ).one()


@asynccontextmanager
async def live_m1_application(settings, case):
    # 用例追加键空间，仍在完整 run_id 下。lifespan/驱动/SQL 均真实执行。
    configured = settings.model_copy(
        update={
            "rate_limit_key_prefix": settings.rate_limit_key_prefix + ":" + case,
        }
    )
    app = create_app(configured)
    async with app.router.lifespan_context(app):
        async with httpx2.AsyncClient(
            transport=httpx2.ASGITransport(app=app, raise_app_exceptions=False),
            base_url="http://m1-check",
        ) as client:
            live = M1Application(app, client, configured)
            try:
                yield live
            finally:
                # 用户和审计保留供核验；只停用本用例造数，
                # 下一用例使用独立的有效管理员集合。
                # 整轮由入口核归属后删除隔离库，不在 fixture 内清库或动 owner。
                if live.user_ids:
                    async with app.state.session_factory() as session, session.begin():
                        await session.execute(
                            update(User)
                            .where(User.id.in_(live.user_ids))
                            .values(status="DISABLED")
                        )


async def overlap_at_lock(monkeypatch, repository, method, first_action, second_action):
    """第一笔持有真实锁时启动第二笔，最终按 HTTP 结果判分，死锁/超时均失败。"""
    held, trying, release = asyncio.Event(), asyncio.Event(), asyncio.Event()
    original = getattr(repository, method)

    async def locked(self, *args, **kwargs):
        is_first = asyncio.current_task().get_name() == "m1-first"
        if not is_first:
            trying.set()
        result = await original(self, *args, **kwargs)
        if is_first:
            held.set()
            await asyncio.wait_for(release.wait(), 5)
        return result

    tasks = []
    with monkeypatch.context() as patch:
        patch.setattr(repository, method, locked)
        try:
            tasks.append(asyncio.create_task(first_action(), name="m1-first"))
            await asyncio.wait_for(held.wait(), 5)
            tasks.append(asyncio.create_task(second_action(), name="m1-second"))
            await asyncio.wait_for(trying.wait(), 5)
            # 仅用有界观察确认第二笔尚未完成；最终必须取得确定的业务响应。
            done, _ = await asyncio.wait([tasks[1]], timeout=0.15)
            assert not done
            release.set()
            return await asyncio.wait_for(asyncio.gather(*tasks), 10)
        finally:
            release.set()
            for task in tasks:
                if not task.done():
                    task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
