from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.audit_log import AuditLog


# 服务先生成安全摘要；仓储只追加/查询，不能独立 commit 破坏业务与审计的原子性。
class AuditLogRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def append(
        self,
        *,
        user_id: int,
        action: str,
        resource_type: str,
        resource_id: int,
        payload_summary: str,
        request_id: str,
        ip: str,
    ) -> None:
        self.session.add(
            AuditLog(
                user_id=user_id,
                action=action,
                resource_type=resource_type,
                resource_id=resource_id,
                payload_summary=payload_summary,
                request_id=request_id,
                ip=ip,
            )
        )
        await self.session.flush()

    async def before(self, cursor: int | None, limit: int) -> list[AuditLog]:
        statement = select(AuditLog).order_by(AuditLog.id.desc()).limit(limit + 1)
        if cursor is not None:
            statement = statement.where(AuditLog.id < cursor)
        # 多取一条判断是否还有下一页，避免满页就错误生成 next_cursor。
        return list((await self.session.scalars(statement)).all())
