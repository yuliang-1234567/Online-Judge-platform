# 服务持有题目锁与事务；测试点及安全审计共同提交，仓储不能独立提交。
import hashlib
import json
import re

from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.exc import TimeoutError as PoolTimeout
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.http import AppError
from app.models.test_case import TestCase
from app.repositories.audit_log import AuditLogRepository
from app.repositories.problem import ProblemRepository
from app.repositories.test_case import TestCaseRepository
from app.schemas.test_case import CaseCreate, CasePage, CaseResponse, CaseUpdate
from app.services.admin import normalize_ip


# 长度前缀消除内容边界歧义；保留原始换行，不根据摘要自动去重。
def calculate_case_metadata(input_data: str, expected_output: str) -> dict:
    input_bytes = input_data.encode("utf-8")
    output_bytes = expected_output.encode("utf-8")
    payload = (
        len(input_bytes).to_bytes(8, "big")
        + input_bytes
        + len(output_bytes).to_bytes(8, "big")
        + output_bytes
    )
    return {
        "input_size": len(input_bytes),
        "output_size": len(output_bytes),
        "sha256": hashlib.sha256(payload).hexdigest(),
    }


def classify_case_error(error: IntegrityError) -> AppError:
    # 只解析 1062 的精确键名，不回传驱动消息或把其他唯一键误认成编号冲突。
    args = getattr(error.orig, "args", ())
    if len(args) >= 2 and args[0] == 1062 and isinstance(args[1], str):
        match = re.search(r"\bfor key (['\x60])([A-Za-z0-9_.]+)\1\Z", args[1])
        if match and match[2].rsplit(".", 1)[-1] == "uk_cases_problem_idx":
            return AppError(409, "CONFLICT", "测试点编号已存在")
    return AppError(500, "INTERNAL_ERROR", "测试点写入失败")


def case_summary(case: TestCase) -> dict:
    # 审计白名单不包含输入、期望输出或原始请求体，删除前也只保留此摘要。
    return {
        field: getattr(case, field)
        for field in (
            "problem_id",
            "case_index",
            "is_sample",
            "input_size",
            "output_size",
            "sha256",
        )
    }


class TestCaseService:
    def __init__(
        self,
        session: AsyncSession,
        problems: ProblemRepository,
        cases: TestCaseRepository,
        audits: AuditLogRepository,
    ) -> None:
        self.session, self.problems, self.cases, self.audits = (
            session,
            problems,
            cases,
            audits,
        )

    async def _writable_problem(self, problem_id: int) -> None:
        problem = await self.problems.lock_by_id(problem_id)
        if problem is None:
            raise AppError(404, "NOT_FOUND", "题目不存在")
        if problem.status not in {"DRAFT", "OFFLINE"}:
            raise AppError(409, "CONFLICT", "题目须下线后再修改")

    async def _require_idle(self, problem_id: int) -> None:
        if await self.problems.has_inflight(problem_id):
            raise AppError(409, "CONFLICT", "题目存在在途提交")

    async def _locked_case(self, case_id: int) -> TestCase:
        # 无锁定位只提供父 ID；取得父锁后必须当前读重取目标，不能信任旧属性。
        problem_id = await self.cases.problem_id_for(case_id)
        if problem_id is None:
            raise AppError(404, "NOT_FOUND", "测试点不存在")
        await self._writable_problem(problem_id)
        case = await self.cases.lock_by_id(case_id, problem_id)
        if case is None:
            raise AppError(404, "NOT_FOUND", "测试点不存在")
        await self._require_idle(problem_id)
        return case

    async def _audit(
        self,
        action: str,
        case_id: int,
        summary: dict,
        *,
        actor_id: int,
        request_id: str,
        ip: str | None,
    ) -> None:
        await self.audits.append(
            user_id=actor_id,
            action=action,
            resource_type="TEST_CASE",
            resource_id=case_id,
            payload_summary=json.dumps(
                summary, ensure_ascii=False, separators=(",", ":")
            )[:2048],
            request_id=request_id,
            ip=normalize_ip(ip),
        )

    async def list_cases(self, problem_id: int, *, page: int, size: int) -> CasePage:
        try:
            async with self.session.begin():
                if await self.problems.by_id(problem_id) is None:
                    raise AppError(404, "NOT_FOUND", "题目不存在")
                rows, total = await self.cases.page(problem_id, page=page, size=size)
                result = CasePage(
                    items=[CaseResponse.model_validate(row) for row in rows],
                    page=page,
                    size=size,
                    total=total,
                )
        except (OperationalError, PoolTimeout):
            raise AppError(503, "SERVICE_UNAVAILABLE", "测试点服务暂时不可用") from None
        return result

    async def create_case(
        self, problem_id: int, data: CaseCreate, **context
    ) -> CaseResponse:
        try:
            async with self.session.begin():
                await self._writable_problem(problem_id)
                await self._require_idle(problem_id)
                if len(await self.cases.locked_ids(problem_id)) >= 50:
                    raise AppError(422, "VALIDATION_ERROR", "每题最多 50 个测试点")
                case = await self.cases.create(
                    problem_id=problem_id,
                    **data.model_dump(),
                    **calculate_case_metadata(data.input_data, data.expected_output),
                )
                await self._audit(
                    "CREATE_TEST_CASE",
                    case.id,
                    {"after": case_summary(case)},
                    **context,
                )
                result = CaseResponse.model_validate(case)
        except IntegrityError as error:
            raise classify_case_error(error) from None
        except (OperationalError, PoolTimeout):
            raise AppError(503, "SERVICE_UNAVAILABLE", "测试点服务暂时不可用") from None
        return result

    async def update_case(
        self, case_id: int, data: CaseUpdate, **context
    ) -> CaseResponse:
        try:
            async with self.session.begin():
                case = await self._locked_case(case_id)
                before = case_summary(case)
                await self.cases.update(
                    case,
                    **data.model_dump(),
                    **calculate_case_metadata(data.input_data, data.expected_output),
                )
                await self._audit(
                    "UPDATE_TEST_CASE",
                    case.id,
                    {"before": before, "after": case_summary(case)},
                    **context,
                )
                result = CaseResponse.model_validate(case)
        except IntegrityError as error:
            raise classify_case_error(error) from None
        except (OperationalError, PoolTimeout):
            raise AppError(503, "SERVICE_UNAVAILABLE", "测试点服务暂时不可用") from None
        return result

    async def delete_case(self, case_id: int, **context) -> None:
        try:
            async with self.session.begin():
                case = await self._locked_case(case_id)
                before = case_summary(case)
                await self.cases.delete(case)
                await self._audit(
                    "DELETE_TEST_CASE", case.id, {"before": before}, **context
                )
        except IntegrityError as error:
            raise classify_case_error(error) from None
        except (OperationalError, PoolTimeout):
            raise AppError(503, "SERVICE_UNAVAILABLE", "测试点服务暂时不可用") from None
