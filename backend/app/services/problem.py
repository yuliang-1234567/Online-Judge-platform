# 管理路由的事务编排：题目、标签关联与审计共提交；不接触 Redis 或测试数据。
import json
import re

from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.exc import TimeoutError as SQLAlchemyTimeoutError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.http import AppError
from app.models.problem import Problem, Tag
from app.repositories.audit_log import AuditLogRepository
from app.repositories.problem import ProblemRepository, TagRepository
from app.schemas.problem import (
    ProblemCreate,
    ProblemDetail,
    ProblemPage,
    ProblemSummary,
    ProblemUpdate,
    TagCreate,
    TagPage,
    TagResponse,
)
from app.services.admin import normalize_ip


def classify_write_error(error: IntegrityError) -> AppError:
    # 驱动只有错误码和消息；只提取约束名，不回显 SQL、参数或原消息。
    # 1062 不是 slug 冲突的充分条件，1452 也不能一律解释为标签缺失。
    args = getattr(error.orig, "args", ())
    if len(args) >= 2 and isinstance(args[1], str):
        if args[0] == 1062:
            match = re.search(
                r"\bfor key (['\x60])(?P<key>[A-Za-z0-9_.]+)\1\Z", args[1]
            )
            key = match["key"].rsplit(".", 1)[-1] if match else None
            if key == "uk_problems_slug":
                return AppError(409, "CONFLICT", "slug 已存在")
            if key == "uk_tags_name":
                return AppError(409, "CONFLICT", "标签已存在")
        if args[0] == 1452:
            match = re.search(
                r"\bCONSTRAINT\s+(['\x60])(?P<key>[A-Za-z0-9_]+)\1\s+FOREIGN KEY\b",
                args[1],
            )
            if match and match["key"] == "fk_problem_tags_tag":
                return AppError(422, "VALIDATION_ERROR", "标签不存在")
    return AppError(500, "INTERNAL_ERROR", "题库写入失败")


def access_summary(problem: Problem, tag_count: int) -> dict:
    # 题面与标题只记长度；标签只记数量，摘要不携带完整业务数据。
    return {
        "slug": problem.slug,
        "difficulty": problem.difficulty,
        "time_limit_ms": problem.time_limit_ms,
        "memory_limit_mb": problem.memory_limit_mb,
        "title_length": len(problem.title),
        "description_bytes": len(problem.description.encode("utf-8")),
        "tag_count": tag_count,
    }


def detail_response(problem: Problem, tags: list[Tag]) -> ProblemDetail:
    return ProblemDetail.model_validate(problem).model_copy(
        update={"tags": [TagResponse.model_validate(tag) for tag in tags]}
    )


class ProblemService:
    def __init__(
        self,
        session: AsyncSession,
        problems: ProblemRepository,
        tags: TagRepository,
        audits: AuditLogRepository,
    ) -> None:
        self.session, self.problems, self.tags, self.audits = (
            session,
            problems,
            tags,
            audits,
        )

    async def _audit(
        self,
        *,
        actor_id: int,
        action: str,
        resource_type: str,
        resource_id: int,
        summary: dict,
        request_id: str,
        ip: str | None,
    ) -> None:
        await self.audits.append(
            user_id=actor_id,
            action=action,
            resource_type=resource_type,
            resource_id=resource_id,
            payload_summary=json.dumps(
                summary, ensure_ascii=False, separators=(",", ":")
            )[:2048],
            request_id=request_id,
            ip=normalize_ip(ip),
        )

    async def create_problem(
        self,
        data: ProblemCreate,
        *,
        actor_id: int,
        request_id: str,
        ip: str | None,
    ) -> ProblemDetail:
        try:
            async with self.session.begin():
                # 预查改善输入错误提示；并发删除仍由物理外键兜底并回滚整笔事务。
                tags = await self.tags.by_ids(data.tag_ids)
                if len(tags) != len(data.tag_ids):
                    raise AppError(422, "VALIDATION_ERROR", "标签不存在")
                problem = await self.problems.create(
                    created_by=actor_id, **data.model_dump(exclude={"tag_ids"})
                )
                await self.problems.replace_tags(problem.id, data.tag_ids)
                await self._audit(
                    actor_id=actor_id,
                    action="CREATE_PROBLEM",
                    resource_type="PROBLEM",
                    resource_id=problem.id,
                    summary={"after": access_summary(problem, len(tags))},
                    request_id=request_id,
                    ip=ip,
                )
                result = detail_response(problem, tags)
        # 转换异常发生在 begin 退出后，flush/关联/审计/commit 的错误共享回滚出口。
        except IntegrityError as error:
            raise classify_write_error(error) from None
        except (OperationalError, SQLAlchemyTimeoutError):
            raise AppError(503, "SERVICE_UNAVAILABLE", "题库服务暂时不可用") from None
        return result

    async def update_problem(
        self,
        problem_id: int,
        data: ProblemUpdate,
        *,
        actor_id: int,
        request_id: str,
        ip: str | None,
    ) -> ProblemDetail:
        try:
            async with self.session.begin():
                problem = await self.problems.lock_by_id(problem_id)
                if problem is None:
                    raise AppError(404, "NOT_FOUND", "题目不存在")
                if problem.status != "DRAFT":
                    raise AppError(409, "CONFLICT", "仅草稿题目允许修改")
                tags = await self.tags.by_ids(data.tag_ids)
                if len(tags) != len(data.tag_ids):
                    raise AppError(422, "VALIDATION_ERROR", "标签不存在")
                old_tags = await self.tags.for_problems([problem_id])
                before = access_summary(problem, len(old_tags.get(problem_id, [])))
                await self.problems.update(
                    problem, **data.model_dump(exclude={"tag_ids"})
                )
                await self.problems.replace_tags(problem_id, data.tag_ids)
                await self._audit(
                    actor_id=actor_id,
                    action="UPDATE_PROBLEM",
                    resource_type="PROBLEM",
                    resource_id=problem_id,
                    summary={
                        "before": before,
                        "after": access_summary(problem, len(tags)),
                    },
                    request_id=request_id,
                    ip=ip,
                )
                result = detail_response(problem, tags)
        except IntegrityError as error:
            raise classify_write_error(error) from None
        except (OperationalError, SQLAlchemyTimeoutError):
            raise AppError(503, "SERVICE_UNAVAILABLE", "题库服务暂时不可用") from None
        return result

    async def create_tag(
        self,
        data: TagCreate,
        *,
        actor_id: int,
        request_id: str,
        ip: str | None,
    ) -> TagResponse:
        try:
            async with self.session.begin():
                tag = await self.tags.create(data.name)
                await self._audit(
                    actor_id=actor_id,
                    action="CREATE_TAG",
                    resource_type="TAG",
                    resource_id=tag.id,
                    summary={"name_length": len(tag.name)},
                    request_id=request_id,
                    ip=ip,
                )
                result = TagResponse.model_validate(tag)
        except IntegrityError as error:
            raise classify_write_error(error) from None
        except (OperationalError, SQLAlchemyTimeoutError):
            raise AppError(503, "SERVICE_UNAVAILABLE", "题库服务暂时不可用") from None
        return result

    async def list_problems(self, *, page: int, size: int) -> ProblemPage:
        try:
            async with self.session.begin():
                rows, total = await self.problems.page(page=page, size=size)
                grouped = await self.tags.for_problems([row["id"] for row in rows])
                result = ProblemPage(
                    items=[
                        ProblemSummary.model_validate(row).model_copy(
                            update={
                                "tags": [
                                    TagResponse.model_validate(tag)
                                    for tag in grouped.get(row["id"], [])
                                ]
                            }
                        )
                        for row in rows
                    ],
                    page=page,
                    size=size,
                    total=total,
                )
        except (OperationalError, SQLAlchemyTimeoutError):
            raise AppError(503, "SERVICE_UNAVAILABLE", "题库服务暂时不可用") from None
        return result

    async def get_problem(self, problem_id: int) -> ProblemDetail:
        try:
            async with self.session.begin():
                problem = await self.problems.by_id(problem_id)
                if problem is None:
                    raise AppError(404, "NOT_FOUND", "题目不存在")
                grouped = await self.tags.for_problems([problem_id])
                result = detail_response(problem, grouped.get(problem_id, []))
        except (OperationalError, SQLAlchemyTimeoutError):
            raise AppError(503, "SERVICE_UNAVAILABLE", "题库服务暂时不可用") from None
        return result

    async def list_tags(self, *, page: int, size: int) -> TagPage:
        try:
            async with self.session.begin():
                tags, total = await self.tags.page(page=page, size=size)
                result = TagPage(
                    items=[TagResponse.model_validate(tag) for tag in tags],
                    page=page,
                    size=size,
                    total=total,
                )
        except (OperationalError, SQLAlchemyTimeoutError):
            raise AppError(503, "SERVICE_UNAVAILABLE", "题库服务暂时不可用") from None
        return result
