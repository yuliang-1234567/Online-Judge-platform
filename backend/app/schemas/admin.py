from datetime import UTC, datetime
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, field_serializer, model_validator

from app.schemas.auth import UserResponse


class UserPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    role: Literal["USER", "ADMIN"] | None = None
    status: Literal["ACTIVE", "DISABLED"] | None = None

    @model_validator(mode="after")
    def require_changes(self) -> Self:
        # 缺省字段表示保持原值；显式 null 与空对象均不能冒充一次有效修改。
        if not self.model_fields_set or any(
            getattr(self, field) is None for field in self.model_fields_set
        ):
            raise ValueError("至少提供一个非空的 role 或 status")
        return self


class UserPage(BaseModel):
    items: list[UserResponse]
    page: int
    size: int
    total: int


class AuditLogResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    user_id: int
    action: str
    resource_type: str
    resource_id: int
    payload_summary: str | None
    request_id: str
    ip: str
    created_at: datetime

    @field_serializer("created_at")
    def serialize_created_at(self, value: datetime) -> str:
        # 与认证响应相同：数据库 DATETIME 使用 UTC，会话中没有时区的值按 UTC 解读。
        if value.tzinfo is None:
            value = value.replace(tzinfo=UTC)
        return (
            value.astimezone(UTC)
            .isoformat(timespec="milliseconds")
            .replace("+00:00", "Z")
        )


class AuditLogPage(BaseModel):
    items: list[AuditLogResponse]
    next_cursor: int | None
