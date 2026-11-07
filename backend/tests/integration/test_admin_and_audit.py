"""管理员命令、集合锁和审计原子性的真实 MySQL 验证，受控入口显式选择。"""

import asyncio
import uuid

import pytest
from m1_support import overlap_at_lock
from sqlalchemy import event, func, select
from sqlalchemy.orm import Session

from app.models.audit_log import AuditLog
from app.models.user import User
from app.repositories.audit_log import AuditLogRepository
from app.repositories.user import UserRepository

ADMIN = "/api/v1/admin/users"


async def audit_count(live, request_id):
    async with live.app.state.session_factory() as session:
        return await session.scalar(
            select(func.count())
            .select_from(AuditLog)
            .where(AuditLog.request_id == request_id)
        )


def test_real_admin_command_login_and_case_collision(m1_application):
    async def scenario():
        async with m1_application("admin-command") as live:
            user_id, name, headers = await live.new_admin()
            before = await live.user_state(user_id)
            assert before.role == "ADMIN" and before.status == "ACTIVE"
            assert before.password_hash.startswith("$argon2id$")
            assert (await live.client.get(ADMIN, headers=headers)).status_code == 200
            assert await live.admin_command(name) == 3
            assert await live.admin_command(name.upper()) == 3
            assert await live.user_state(user_id) == before
            async with live.app.state.session_factory() as session:
                # ai_ci 排序规则下大小写查询命中同一行。
                count = await session.scalar(
                    select(func.count())
                    .select_from(User)
                    .where(User.username == name.upper())
                )
            assert count == 1

    asyncio.run(scenario())


@pytest.mark.parametrize("reverse", [False, True])
def test_real_two_admin_removals_serialize(m1_application, monkeypatch, reverse):
    async def scenario():
        async with m1_application("last-admin-" + str(reverse)) as live:
            admins = [await live.new_admin(), await live.new_admin()]
            if reverse:
                admins.reverse()
            (first_id, _, first_headers), (second_id, _, second_headers) = admins
            first_request, second_request = uuid.uuid4().hex, uuid.uuid4().hex

            async def first():
                return await live.client.patch(
                    f"{ADMIN}/{second_id}",
                    json={"status": "DISABLED"},
                    headers={**first_headers, "X-Request-ID": first_request},
                )

            async def second():
                return await live.client.patch(
                    f"{ADMIN}/{first_id}",
                    json={"status": "DISABLED"},
                    headers={**second_headers, "X-Request-ID": second_request},
                )

            responses = await overlap_at_lock(
                monkeypatch, UserRepository, "lock_active_admin_ids", first, second
            )
            assert [r.status_code for r in responses] == [200, 409]
            assert (await live.user_state(first_id)).status == "ACTIVE"
            assert (await live.user_state(second_id)).status == "DISABLED"
            assert await audit_count(live, first_request) == 1
            assert await audit_count(live, second_request) == 0

    asyncio.run(scenario())


def test_real_last_admin_rejection_is_atomic(m1_application):
    async def scenario():
        async with m1_application("last-admin-reject") as live:
            user_id, _, headers = await live.new_admin()
            before = await live.user_state(user_id)
            request_id = uuid.uuid4().hex
            response = await live.client.patch(
                f"{ADMIN}/{user_id}",
                json={"role": "USER", "status": "DISABLED"},
                headers={**headers, "X-Request-ID": request_id},
            )
            assert response.status_code == 409
            assert await live.user_state(user_id) == before
            assert await audit_count(live, request_id) == 0

    asyncio.run(scenario())


@pytest.mark.parametrize("stage", ["audit", "commit"])
def test_real_admin_fault_rolls_back_flushed_access(m1_application, monkeypatch, stage):
    async def scenario():
        async with m1_application("admin-fault-" + stage) as live:
            _, _, actor = await live.new_admin()
            target_id, _, _ = await live.new_admin()
            before = await live.user_state(target_id)
            request_id = uuid.uuid4().hex
            if stage == "audit":
                original = AuditLogRepository.append

                async def fail(self, **values):
                    await original(self, **values)
                    raise RuntimeError("injected audit fault")

                monkeypatch.setattr(AuditLogRepository, "append", fail)
            else:
                original = UserRepository.update_access

                async def mark(self, user, **values):
                    await original(self, user, **values)
                    self.session.sync_session.info["m1_commit_fault"] = True

                def fail_commit(session):
                    if session.info.pop("m1_commit_fault", False):
                        raise RuntimeError("injected pre-commit fault")

                monkeypatch.setattr(UserRepository, "update_access", mark)
                event.listen(Session, "before_commit", fail_commit)
            try:
                response = await live.client.patch(
                    f"{ADMIN}/{target_id}",
                    json={"role": "USER", "status": "DISABLED"},
                    headers={**actor, "X-Request-ID": request_id},
                )
                assert response.status_code == 500
                assert await live.user_state(target_id) == before
                assert await audit_count(live, request_id) == 0
            finally:
                if stage == "commit":
                    event.remove(Session, "before_commit", fail_commit)

    asyncio.run(scenario())


def test_real_same_token_sees_admin_role_and_status_changes(m1_application):
    async def scenario():
        async with m1_application("admin-token") as live:
            _, _, actor = await live.new_admin()
            target_id, target_name, target = await live.new_admin()
            assert (
                await live.client.patch(
                    f"{ADMIN}/{target_id}", json={"role": "USER"}, headers=actor
                )
            ).status_code == 200
            assert (await live.client.get(ADMIN, headers=target)).status_code == 403
            me = await live.client.get("/api/v1/auth/me", headers=target)
            assert me.status_code == 200 and me.json()["role"] == "USER"
            assert (
                await live.client.patch(
                    f"{ADMIN}/{target_id}", json={"status": "DISABLED"}, headers=actor
                )
            ).status_code == 200
            assert (
                await live.client.get("/api/v1/auth/me", headers=target)
            ).status_code == 403
            assert (
                await live.client.patch(
                    f"{ADMIN}/{target_id}", json={"status": "ACTIVE"}, headers=actor
                )
            ).status_code == 200
            assert (
                await live.client.get("/api/v1/auth/me", headers=target)
            ).status_code == 200
            assert await live.login(target_name)

    asyncio.run(scenario())
