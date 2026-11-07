"""题库与测试点真实事务验证；提交记录仅隔离库手工造数，非提交端到端。"""

import asyncio
import json
import uuid

import pytest
from m1_support import overlap_at_lock
from sqlalchemy import delete, event, func, insert, select, text
from sqlalchemy.orm import Session

from app.models.audit_log import AuditLog
from app.models.problem import Problem, Tag
from app.models.test_case import TestCase as Case
from app.repositories.audit_log import AuditLogRepository
from app.repositories.problem import ProblemRepository, TagRepository
from app.services.test_case import calculate_case_metadata

ADMIN = "/api/v1/admin"
PUBLIC = "/api/v1/problems"


def problem_fields(**changes):
    return {
        "title": "M1 draft",
        "description": "M1 markdown",
        "difficulty": "EASY",
        "tag_ids": [],
        "time_limit_ms": 1000,
        "memory_limit_mb": 256,
        **changes,
    }


def case_fields(index=1, sample=False, **changes):
    return {
        "case_index": index,
        "input_data": "中\n",
        "expected_output": "OK\n",
        "is_sample": sample,
        **changes,
    }


async def new_problem(live, headers, **fields):
    response = await live.client.post(
        f"{ADMIN}/problems",
        headers=headers,
        json={"slug": "m1-" + uuid.uuid4().hex, **problem_fields(**fields)},
    )
    assert response.status_code == 201
    return response.json()


async def new_case(live, headers, problem_id, **fields):
    response = await live.client.post(
        f"{ADMIN}/problems/{problem_id}/test-cases",
        headers=headers,
        json=case_fields(**fields),
    )
    assert response.status_code == 201
    return response.json()


async def audit_count(live, request_id):
    async with live.app.state.session_factory() as session:
        return await session.scalar(
            select(func.count())
            .select_from(AuditLog)
            .where(AuditLog.request_id == request_id)
        )


async def seed_submission(live, user_id, problem_id, status):
    # 所有必填快照和幂等字段均造合法值；只证明编辑侧面对现存记录的行为。
    async with live.app.state.session_factory() as session, session.begin():
        result = await session.execute(
            text(
                "INSERT INTO submissions "
                "(user_id, problem_id, language, code, time_limit_ms_snapshot, "
                "memory_limit_mb_snapshot, status, request_id, idempotency_key, "
                "queued_at) "
                "VALUES (:user, :problem, 'python', 'print(1)', 1000, 256, :status, "
                ":request, :idem, UTC_TIMESTAMP(3))"
            ),
            {
                "user": user_id,
                "problem": problem_id,
                "status": status,
                "request": uuid.uuid4().hex,
                "idem": uuid.uuid4().hex,
            },
        )
        return result.lastrowid


def test_real_problem_publication_lifecycle_and_whitelist(m1_application):
    async def scenario():
        async with m1_application("problem-lifecycle") as live:
            _, _, headers = await live.new_admin()
            tag = await live.client.post(
                f"{ADMIN}/tags",
                headers=headers,
                json={"name": "tag-" + uuid.uuid4().hex[:16]},
            )
            assert tag.status_code == 201
            row = await new_problem(live, headers, tag_ids=[tag.json()["id"]])
            problem_id = row["id"]
            assert (await live.client.get(f"{PUBLIC}/{problem_id}")).status_code == 404
            assert (
                await live.client.get(f"{ADMIN}/problems/{problem_id}")
            ).status_code == 401
            sample = await new_case(live, headers, problem_id, sample=True)
            hidden = await new_case(
                live,
                headers,
                problem_id,
                index=2,
                input_data="hidden-input-marker",
                expected_output="hidden-output-marker",
            )
            cases = await live.client.get(
                f"{ADMIN}/problems/{problem_id}/test-cases", headers=headers
            )
            assert cases.status_code == 200 and cases.json()["total"] == 2
            changed = await live.client.put(
                f"{ADMIN}/problems/{problem_id}",
                headers=headers,
                json=problem_fields(title="Changed", tag_ids=[tag.json()["id"]]),
            )
            assert changed.status_code == 200
            url = f"{ADMIN}/problems/{problem_id}"
            assert (
                await live.client.post(url + "/publish", headers=headers)
            ).status_code == 200
            detail = await live.client.get(f"{PUBLIC}/{problem_id}")
            assert detail.status_code == 200
            payload = detail.json()
            assert set(payload) == {
                "id",
                "slug",
                "title",
                "description",
                "difficulty",
                "time_limit_ms",
                "memory_limit_mb",
                "tags",
                "samples",
            }
            assert payload["samples"] == [
                {
                    "case_index": 1,
                    "input_data": sample["input_data"],
                    "expected_output": sample["expected_output"],
                }
            ]
            assert "hidden-input-marker" not in detail.text
            assert "hidden-output-marker" not in detail.text
            listing = await live.client.get(PUBLIC, params={"q": row["slug"]})
            assert listing.status_code == 200 and listing.json()["total"] == 1
            assert "description" not in listing.json()["items"][0]
            assert (
                await live.client.put(url, headers=headers, json=problem_fields())
            ).status_code == 409
            assert (
                await live.client.post(url + "/offline", headers=headers)
            ).status_code == 200
            assert (await live.client.get(f"{PUBLIC}/{problem_id}")).status_code == 404
            assert (
                await live.client.put(
                    f"{ADMIN}/test-cases/{hidden['id']}",
                    headers=headers,
                    json=case_fields(index=2, input_data="changed-hidden"),
                )
            ).status_code == 200
            assert (
                await live.client.post(url + "/publish", headers=headers)
            ).status_code == 200
            audits = await live.client.get(f"{ADMIN}/audit-logs", headers=headers)
            assert audits.status_code == 200
            assert (
                "hidden-input-marker" not in audits.text
                and "changed-hidden" not in audits.text
            )

    asyncio.run(scenario())


def test_real_unique_slug_and_collated_tag_conflicts(m1_application):
    async def scenario():
        async with m1_application("problem-unique") as live:
            _, _, headers = await live.new_admin()
            row = await new_problem(live, headers)
            response = await live.client.post(
                f"{ADMIN}/problems",
                headers=headers,
                json={"slug": row["slug"], **problem_fields()},
            )
            assert response.status_code == 409
            name = "t-" + uuid.uuid4().hex[:16]
            assert (
                await live.client.post(
                    f"{ADMIN}/tags", headers=headers, json={"name": name + "É"}
                )
            ).status_code == 201
            response = await live.client.post(
                f"{ADMIN}/tags", headers=headers, json={"name": name.upper() + "e"}
            )
            assert response.status_code == 409
            assert "uk_tags_name" not in response.text
            async with live.app.state.session_factory() as session:
                assert (
                    await session.scalar(
                        select(func.count())
                        .select_from(Problem)
                        .where(Problem.slug == row["slug"])
                    )
                    == 1
                )
                collation = await session.scalar(
                    text(
                        "SELECT COLLATION_NAME FROM INFORMATION_SCHEMA.COLUMNS "
                        "WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME='tags' "
                        "AND COLUMN_NAME='name'"
                    )
                )
                assert collation == "utf8mb4_0900_ai_ci"

    asyncio.run(scenario())


def test_real_tag_foreign_key_race_rolls_back_problem(m1_application, monkeypatch):
    async def scenario():
        async with m1_application("tag-foreign-key") as live:
            _, _, headers = await live.new_admin()
            tag = await live.client.post(
                f"{ADMIN}/tags",
                headers=headers,
                json={"name": "fk-" + uuid.uuid4().hex[:12]},
            )
            tag_id = tag.json()["id"]
            original = TagRepository.by_ids

            async def disappear(self, ids):
                rows = await original(self, ids)
                async with live.app.state.session_factory() as session, session.begin():
                    await session.execute(delete(Tag).where(Tag.id == tag_id))
                return rows

            monkeypatch.setattr(TagRepository, "by_ids", disappear)
            slug, request_id = "fk-" + uuid.uuid4().hex, uuid.uuid4().hex
            response = await live.client.post(
                f"{ADMIN}/problems",
                headers={**headers, "X-Request-ID": request_id},
                json={"slug": slug, **problem_fields(tag_ids=[tag_id])},
            )
            assert response.status_code == 422
            assert response.json()["error"]["message"] == "标签不存在"
            assert "fk_problem_tags_tag" not in response.text
            async with live.app.state.session_factory() as session:
                assert (
                    await session.scalar(
                        select(func.count())
                        .select_from(Problem)
                        .where(Problem.slug == slug)
                    )
                    == 0
                )
            assert await audit_count(live, request_id) == 0

    asyncio.run(scenario())


def test_real_case_number_conflict_and_fifty_limit(m1_application, monkeypatch):
    async def scenario():
        async with m1_application("case-capacity") as live:
            _, _, headers = await live.new_admin()
            row = await new_problem(live, headers)
            # 批量造 49 个合法测试点，随后两个 HTTP 请求在同一父锁下争夺第 50 个名额。
            values = [
                {
                    "problem_id": row["id"],
                    **case_fields(index=i),
                    **calculate_case_metadata("中\n", "OK\n"),
                }
                for i in range(1, 50)
            ]
            async with live.app.state.session_factory() as session, session.begin():
                await session.execute(insert(Case), values)
            url = f"{ADMIN}/problems/{row['id']}/test-cases"
            duplicate = await live.client.post(
                url, headers=headers, json=case_fields(index=1)
            )
            assert duplicate.status_code == 409

            async def first():
                return await live.client.post(
                    url, headers=headers, json=case_fields(index=50)
                )

            async def second():
                return await live.client.post(
                    url, headers=headers, json=case_fields(index=51)
                )

            responses = await overlap_at_lock(
                monkeypatch, ProblemRepository, "lock_by_id", first, second
            )
            assert [r.status_code for r in responses] == [201, 422]
            async with live.app.state.session_factory() as session:
                assert (
                    await session.scalar(
                        select(func.count())
                        .select_from(Case)
                        .where(Case.problem_id == row["id"])
                    )
                    == 50
                )

    asyncio.run(scenario())


@pytest.mark.parametrize("first_write", ["create", "limit", "publish"])
def test_real_publication_serializes_with_edits(
    m1_application, monkeypatch, first_write
):
    async def scenario():
        async with m1_application("publish-lock-" + first_write) as live:
            _, _, headers = await live.new_admin()
            row = await new_problem(live, headers)
            await new_case(live, headers, row["id"], sample=True)
            url = f"{ADMIN}/problems/{row['id']}"

            async def create():
                return await live.client.post(
                    url + "/test-cases", headers=headers, json=case_fields(index=2)
                )

            async def limit():
                return await live.client.put(
                    url, headers=headers, json=problem_fields(time_limit_ms=200_000)
                )

            async def publish():
                return await live.client.post(url + "/publish", headers=headers)

            first = {"create": create, "limit": limit, "publish": publish}[first_write]
            second = create if first_write == "publish" else publish
            responses = await overlap_at_lock(
                monkeypatch, ProblemRepository, "lock_by_id", first, second
            )
            expected = {
                "create": [201, 200],
                "limit": [200, 409],
                "publish": [200, 409],
            }
            assert [r.status_code for r in responses] == expected[first_write]
            async with live.app.state.session_factory() as session:
                current = await session.get(Problem, row["id"])
                assert current.status == (
                    "DRAFT" if first_write == "limit" else "PUBLISHED"
                )
                count = await session.scalar(
                    select(func.count())
                    .select_from(Case)
                    .where(Case.problem_id == row["id"])
                )
                assert count == (2 if first_write == "create" else 1)
                if first_write == "create":
                    summary = await session.scalar(
                        select(AuditLog.payload_summary)
                        .where(
                            AuditLog.resource_id == row["id"],
                            AuditLog.action == "PUBLISH_PROBLEM",
                        )
                        .order_by(AuditLog.id.desc())
                    )
                    assert json.loads(summary)["case_count"] == 2

    asyncio.run(scenario())


@pytest.mark.parametrize("status", ["QUEUED", "RUNNING"])
def test_real_seeded_inflight_refuses_changes_only_when_required(
    m1_application, status
):
    async def scenario():
        async with m1_application("inflight-" + status) as live:
            user_id, _, headers = await live.new_admin()
            row = await new_problem(live, headers)
            case = await new_case(live, headers, row["id"], sample=True)
            sub_id = await seed_submission(live, user_id, row["id"], status)
            url = f"{ADMIN}/problems/{row['id']}"
            operations = [
                ("post", url + "/test-cases", case_fields(index=2)),
                ("put", f"{ADMIN}/test-cases/{case['id']}", case_fields(sample=True)),
                ("delete", f"{ADMIN}/test-cases/{case['id']}", None),
                ("put", url, problem_fields(time_limit_ms=999)),
            ]
            for method, endpoint, body in operations:
                request_id = uuid.uuid4().hex
                options = {"headers": {**headers, "X-Request-ID": request_id}}
                if body is not None:
                    options["json"] = body
                response = await live.client.request(method, endpoint, **options)
                assert response.status_code == 409
                assert await audit_count(live, request_id) == 0
            assert (
                await live.client.put(
                    url, headers=headers, json=problem_fields(title="Only text changed")
                )
            ).status_code == 200
            async with live.app.state.session_factory() as session:
                current = await session.get(Problem, row["id"])
                assert current.time_limit_ms == 1000
                assert await session.get(Case, case["id"]) is not None
            async with live.app.state.session_factory() as session, session.begin():
                await session.execute(
                    text("UPDATE submissions SET status='ACCEPTED' WHERE id=:id"),
                    {"id": sub_id},
                )
            assert (
                await live.client.put(
                    url, headers=headers, json=problem_fields(time_limit_ms=999)
                )
            ).status_code == 200

    asyncio.run(scenario())


@pytest.mark.parametrize("operation", ["case", "publish"])
@pytest.mark.parametrize("stage", ["audit", "commit"])
def test_real_problem_fault_rolls_back_business_and_audit(
    m1_application, monkeypatch, operation, stage
):
    async def scenario():
        async with m1_application("problem-fault-" + operation + stage) as live:
            _, _, headers = await live.new_admin()
            row = await new_problem(live, headers)
            case = await new_case(live, headers, row["id"], sample=True)
            request_id = uuid.uuid4().hex
            original_audit = AuditLogRepository.append

            async def faulting_audit(self, **values):
                await original_audit(self, **values)
                if stage == "audit":
                    raise RuntimeError("injected audit fault")
                self.session.sync_session.info["m1_commit_fault"] = True

            def fail_commit(session):
                if session.info.pop("m1_commit_fault", False):
                    raise RuntimeError("injected pre-commit fault")

            monkeypatch.setattr(AuditLogRepository, "append", faulting_audit)
            event.listen(Session, "before_commit", fail_commit)
            try:
                context = {**headers, "X-Request-ID": request_id}
                if operation == "case":
                    response = await live.client.put(
                        f"{ADMIN}/test-cases/{case['id']}",
                        headers=context,
                        json=case_fields(sample=True, input_data="changed-uncommitted"),
                    )
                else:
                    response = await live.client.post(
                        f"{ADMIN}/problems/{row['id']}/publish", headers=context
                    )
                assert response.status_code == 500
                async with live.app.state.session_factory() as session:
                    assert (await session.get(Case, case["id"])).input_data == case[
                        "input_data"
                    ]
                    assert (await session.get(Problem, row["id"])).status == "DRAFT"
                assert await audit_count(live, request_id) == 0
            finally:
                event.remove(Session, "before_commit", fail_commit)

    asyncio.run(scenario())


def test_real_deleted_case_sets_historical_foreign_key_null(m1_application):
    async def scenario():
        async with m1_application("case-set-null") as live:
            user_id, _, headers = await live.new_admin()
            row = await new_problem(live, headers)
            case = await new_case(live, headers, row["id"], sample=True)
            sub_id = await seed_submission(live, user_id, row["id"], "ACCEPTED")
            async with live.app.state.session_factory() as session, session.begin():
                result = await session.execute(
                    text(
                        "INSERT INTO submission_cases "
                        "(submission_id, test_case_id, case_index, is_sample, status) "
                        "VALUES (:sub, :case, 1, 1, 'ACCEPTED')"
                    ),
                    {"sub": sub_id, "case": case["id"]},
                )
                history_id = result.lastrowid
            response = await live.client.delete(
                f"{ADMIN}/test-cases/{case['id']}", headers=headers
            )
            assert response.status_code == 204
            async with live.app.state.session_factory() as session:
                history = (
                    await session.execute(
                        text(
                            "SELECT test_case_id, case_index, is_sample, status "
                            "FROM submission_cases WHERE id=:id"
                        ),
                        {"id": history_id},
                    )
                ).one()
                assert tuple(history) == (None, 1, 1, "ACCEPTED")

    asyncio.run(scenario())
