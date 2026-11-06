import json
from collections.abc import Mapping, Sequence
from typing import Literal

from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.exc import TimeoutError as PoolTimeout
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.http import AppError
from app.models.problem import Problem, Tag
from app.repositories.audit_log import AuditLogRepository
from app.repositories.problem import ProblemRepository, TagRepository
from app.repositories.test_case import TestCaseRepository
from app.schemas.public_problem import (
    PublicProblemDetail,
    PublicProblemPage,
    PublicProblemSummary,
    PublicSample,
    PublicTag,
)
from app.services.admin import normalize_ip

# 设计 §8.4（第 663 行）的估算公式和 task_time_limit=180（第 649 行）。
# Worker 接入时应核对实际硬上限与这里的发布门槛。
PER_CASE_OVERHEAD_MS = 2_000
TASK_OVERHEAD_MS = 20_000
TASK_HARD_LIMIT_MS = 180_000


def validate_publication(problem: Problem, cases: Sequence[tuple[int, bool]]) -> int:
    """检查锁定后的当前题目及测试点，返回用于审计的整数毫秒预算。"""
    if not cases:
        raise AppError(409, "CONFLICT", "发布至少需要一个测试点")
    if not any(is_sample for _, is_sample in cases):
        raise AppError(409, "CONFLICT", "发布至少需要一个样例")
    limits = (problem.time_limit_ms, problem.memory_limit_mb)
    if any(
        type(value) is not int or not 1 <= value <= 4_294_967_295 for value in limits
    ):
        raise AppError(409, "CONFLICT", "题目限制不合法，无法发布")
    budget_ms = len(cases) * (problem.time_limit_ms + PER_CASE_OVERHEAD_MS)
    budget_ms += TASK_OVERHEAD_MS
    if budget_ms > TASK_HARD_LIMIT_MS:
        raise AppError(
            409, "CONFLICT", "题目时间预算超过发布上限，请减少测试点或降低时限"
        )
    return budget_ms


def public_summary(row: Mapping, tags: Sequence[Tag]) -> PublicProblemSummary:
    return PublicProblemSummary(
        id=row["id"],
        slug=row["slug"],
        title=row["title"],
        difficulty=row["difficulty"],
        time_limit_ms=row["time_limit_ms"],
        memory_limit_mb=row["memory_limit_mb"],
        tags=[PublicTag.model_validate(tag) for tag in tags],
    )


def public_detail(
    row: Mapping, tags: Sequence[Tag], samples: Sequence[Mapping]
) -> PublicProblemDetail:
    # 仓储只取公开样例，响应再按字段白名单组装，避免管理 DTO 的字段渗透。
    return PublicProblemDetail(
        **public_summary(row, tags).model_dump(),
        description=row["description"],
        samples=[
            PublicSample(
                case_index=sample["case_index"],
                input_data=sample["input_data"],
                expected_output=sample["expected_output"],
            )
            for sample in samples
        ],
    )


class ProblemPublicationService:
    def __init__(
        self,
        session: AsyncSession,
        problems: ProblemRepository,
        tags: TagRepository,
        cases: TestCaseRepository,
        audits: AuditLogRepository,
    ) -> None:
        self.session = session
        self.problems = problems
        self.tags = tags
        self.cases = cases
        self.audits = audits

    async def transition(
        self,
        problem_id: int,
        target: Literal["PUBLISHED", "OFFLINE"],
        *,
        actor_id: int,
        request_id: str,
        ip: str | None,
    ) -> dict:
        try:
            async with self.session.begin():
                # 与测试点写入共用父锁，先锁题目再读测试点，避免门槛判定过期。
                problem = await self.problems.lock_by_id(problem_id)
                if problem is None:
                    raise AppError(404, "NOT_FOUND", "题目不存在")
                previous = problem.status
                summary = {"before": previous, "after": target}
                if target == "PUBLISHED":
                    if previous not in {"DRAFT", "OFFLINE"}:
                        raise AppError(409, "CONFLICT", "题目已发布")
                    cases = await self.cases.locked_publication_rows(problem_id)
                    summary["budget_ms"] = validate_publication(problem, cases)
                    summary["case_count"] = len(cases)
                    action = "PUBLISH_PROBLEM"
                else:
                    if previous != "PUBLISHED":
                        raise AppError(409, "CONFLICT", "只有已发布题目可以下线")
                    action = "OFFLINE_PROBLEM"
                await self.problems.set_status(problem, target)
                await self.audits.append(
                    user_id=actor_id,
                    action=action,
                    resource_type="PROBLEM",
                    resource_id=problem_id,
                    payload_summary=json.dumps(summary, separators=(",", ":")),
                    request_id=request_id,
                    ip=normalize_ip(ip),
                )
        except IntegrityError:
            raise AppError(500, "INTERNAL_ERROR", "题目状态写入失败") from None
        except (OperationalError, PoolTimeout):
            raise AppError(503, "SERVICE_UNAVAILABLE", "题库服务暂时不可用") from None
        return {"id": problem_id, "status": target}

    async def list_public(
        self,
        *,
        page: int,
        size: int,
        difficulty: str | None,
        tag_id: int | None,
        q: str | None,
    ) -> PublicProblemPage:
        try:
            async with self.session.begin():
                rows, total = await self.problems.page_published(
                    page=page,
                    size=size,
                    difficulty=difficulty,
                    tag_id=tag_id,
                    q=q.strip() if q else "",
                )
                grouped = await self.tags.for_problems([row["id"] for row in rows])
                return PublicProblemPage(
                    items=[
                        public_summary(row, grouped.get(row["id"], [])) for row in rows
                    ],
                    page=page,
                    size=size,
                    total=total,
                )
        except (OperationalError, PoolTimeout):
            raise AppError(503, "SERVICE_UNAVAILABLE", "题库服务暂时不可用") from None

    async def get_public(self, problem_id: int) -> PublicProblemDetail:
        try:
            async with self.session.begin():
                row = await self.problems.published_by_id(problem_id)
                if row is None:
                    raise AppError(404, "NOT_FOUND", "题目不存在")
                # InnoDB 默认 RR 下三次非锁定读共享该事务的读快照。
                grouped = await self.tags.for_problems([problem_id])
                samples = await self.cases.public_samples(problem_id)
                return public_detail(row, grouped.get(problem_id, []), samples)
        except (OperationalError, PoolTimeout):
            raise AppError(503, "SERVICE_UNAVAILABLE", "题库服务暂时不可用") from None
