# 本节只有管理 DTO；未来公开接口另建白名单，不能直接复用管理详情。
import re
from datetime import UTC, datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_serializer, field_validator

PositiveId = Annotated[int, Field(strict=True, gt=0, le=18446744073709551615)]
LimitValue = Annotated[int, Field(strict=True, gt=0, le=4294967295)]


class ProblemFields(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1, max_length=128)
    description: str = Field(min_length=1)
    difficulty: Literal["EASY", "MEDIUM", "HARD"]
    tag_ids: list[PositiveId]
    time_limit_ms: LimitValue
    memory_limit_mb: LimitValue

    @field_validator("title", mode="before")
    @classmethod
    def trim_title(cls, value):
        return value.strip() if isinstance(value, str) else value

    @field_validator("description")
    @classmethod
    def require_description(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("题面不能为空")
        return value

    @field_validator("tag_ids")
    @classmethod
    def unique_tags(cls, value: list[int]) -> list[int]:
        if len(value) != len(set(value)):
            raise ValueError("标签 ID 不得重复")
        return value


class ProblemCreate(ProblemFields):
    slug: str = Field(min_length=1, max_length=64)
    tag_ids: list[PositiveId] = Field(default_factory=list)
    time_limit_ms: LimitValue = 1000
    memory_limit_mb: LimitValue = 256

    @field_validator("slug")
    @classmethod
    def require_slug(cls, value: str) -> str:
        if re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", value) is None:
            raise ValueError("slug 格式不合法")
        return value


# 六字段没有默认值；PUT 是全量替换，省略不能被解释成保持旧值。
class ProblemUpdate(ProblemFields):
    pass


class TagCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=32)

    @field_validator("name", mode="before")
    @classmethod
    def trim_name(cls, value):
        return value.strip() if isinstance(value, str) else value


class UTCResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    @field_serializer("created_at", "updated_at", check_fields=False)
    def utc_time(self, value: datetime) -> str:
        if value.tzinfo is None:
            value = value.replace(tzinfo=UTC)
        return (
            value.astimezone(UTC)
            .isoformat(timespec="milliseconds")
            .replace("+00:00", "Z")
        )


class TagResponse(UTCResponse):
    id: int
    name: str
    created_at: datetime


class ProblemSummary(UTCResponse):
    id: int
    slug: str
    title: str
    difficulty: Literal["EASY", "MEDIUM", "HARD"]
    time_limit_ms: int
    memory_limit_mb: int
    status: Literal["DRAFT", "PUBLISHED", "OFFLINE"]
    created_by: int
    created_at: datetime
    updated_at: datetime
    tags: list[TagResponse] = Field(default_factory=list)


class ProblemDetail(ProblemSummary):
    description: str


class ProblemPage(BaseModel):
    items: list[ProblemSummary]
    page: int
    size: int
    total: int


class TagPage(BaseModel):
    items: list[TagResponse]
    page: int
    size: int
    total: int
