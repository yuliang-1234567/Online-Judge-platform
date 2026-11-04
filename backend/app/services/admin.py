# 管理路由进入此处；服务拥有事务，仓储只执行 SQL，不掌管请求会话的关闭。
import ipaddress
import json

from sqlalchemy.exc import OperationalError
from sqlalchemy.exc import TimeoutError as SQLAlchemyTimeoutError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.http import AppError
from app.models.user import User
from app.repositories.audit_log import AuditLogRepository
from app.repositories.user import UserRepository
from app.schemas.admin import AuditLogPage, AuditLogResponse, UserPage, UserPatch
from app.schemas.auth import UserResponse


def normalize_ip(ip: str | None) -> str:
    # 只使用服务器提供的 peer，不信任请求头；缺失/非法 peer 用固定哨兵，不能伪造 IP。
    try:
        return ipaddress.ip_address(ip).compressed if ip is not None else "unknown"
    except ValueError:
        return "unknown"


def summarize_access(before: tuple[str, str], after: User) -> str:
    # 先挑角色/状态构造摘要，再按字符截断；不遍历 ORM 属性或截取原始请求体。
    summary = {
        "before": {"role": before[0], "status": before[1]},
        "after": {"role": after.role, "status": after.status},
    }
    return json.dumps(summary, ensure_ascii=False, separators=(",", ":"))[:2048]


class AdminService:
    def __init__(
        self,
        session: AsyncSession,
        users: UserRepository,
        audits: AuditLogRepository,
    ) -> None:
        self.session = session
        self.users = users
        self.audits = audits

    async def list_users(
        self, *, page: int, size: int, username: str | None
    ) -> UserPage:
        try:
            async with self.session.begin():
                users, total = await self.users.page(
                    page=page, size=size, username=username
                )
                result = UserPage(
                    items=[UserResponse.model_validate(user) for user in users],
                    page=page,
                    size=size,
                    total=total,
                )
        except (OperationalError, SQLAlchemyTimeoutError):
            raise AppError(503, "SERVICE_UNAVAILABLE", "管理服务暂时不可用") from None
        return result

    async def patch_user(
        self,
        user_id: int,
        data: UserPatch,
        *,
        actor_id: int,
        request_id: str,
        ip: str | None,
    ) -> UserResponse:
        try:
            async with self.session.begin():
                # 先锁整个有效管理员集合，再锁目标。
                # 只锁不同目标行不能保护跨行不变量。
                # 纯晋升/激活不会减少集合，不主动取此保护锁；混合降权/禁用仍要先取锁。
                admin_ids = None
                if data.role == "USER" or data.status == "DISABLED":
                    admin_ids = await self.users.lock_active_admin_ids()
                target = await self.users.lock_by_id(user_id)
                if target is None:
                    raise AppError(404, "NOT_FOUND", "用户不存在")
                role = data.role if data.role is not None else target.role
                status = data.status if data.status is not None else target.status
                if (
                    target.role == "ADMIN"
                    and target.status == "ACTIVE"
                    and (role != "ADMIN" or status != "ACTIVE")
                    and admin_ids is not None
                    and len(admin_ids) <= 1
                ):
                    raise AppError(409, "CONFLICT", "不能移除最后一名有效管理员")
                before = (target.role, target.status)
                await self.users.update_access(target, role=role, status=status)
                await self.audits.append(
                    user_id=actor_id,
                    action="UPDATE_USER",
                    resource_type="USER",
                    resource_id=target.id,
                    payload_summary=summarize_access(before, target),
                    request_id=request_id,
                    ip=normalize_ip(ip),
                )
                # 在事务内完成白名单转换；审计 flush 或 commit 失败都不能返回成功。
                result = UserResponse.model_validate(target)
        except (OperationalError, SQLAlchemyTimeoutError):
            raise AppError(503, "SERVICE_UNAVAILABLE", "管理服务暂时不可用") from None
        return result

    async def list_audits(self, *, cursor: int | None, limit: int) -> AuditLogPage:
        try:
            async with self.session.begin():
                rows = await self.audits.before(cursor, limit)
                visible = rows[:limit]
                result = AuditLogPage(
                    items=[AuditLogResponse.model_validate(row) for row in visible],
                    next_cursor=visible[-1].id if len(rows) > limit else None,
                )
        except (OperationalError, SQLAlchemyTimeoutError):
            raise AppError(503, "SERVICE_UNAVAILABLE", "管理服务暂时不可用") from None
        return result
