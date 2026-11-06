# 仅管理员可使用完整数据 DTO；原始内容不裁剪，大小按 UTF-8 字节校验。
from datetime import datetime
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.schemas.problem import UTCResponse

DATA_LIMIT = 1024 * 1024
CaseIndex = Annotated[int, Field(strict=True, gt=0, le=4294967295)]


class CaseFields(BaseModel):
    model_config = ConfigDict(extra="forbid")

    case_index: CaseIndex
    is_sample: bool = Field(strict=True)
    input_data: str = Field(strict=True)
    expected_output: str = Field(strict=True)

    @field_validator("input_data", "expected_output")
    @classmethod
    def validate_bytes(cls, value: str) -> str:
        try:
            encoded = value.encode("utf-8")
        except UnicodeEncodeError:
            raise ValueError("测试内容必须是有效 UTF-8") from None
        if len(encoded) > DATA_LIMIT:
            raise ValueError("测试内容超过字节上限")
        return value


class CaseCreate(CaseFields):
    is_sample: bool = Field(default=False, strict=True)


class CaseUpdate(CaseFields):
    pass


class CaseResponse(UTCResponse):
    id: int
    problem_id: int
    case_index: int
    is_sample: bool
    input_data: str
    expected_output: str
    input_size: int
    output_size: int
    sha256: str
    created_at: datetime
    updated_at: datetime


class CasePage(BaseModel):
    items: list[CaseResponse]
    page: int
    size: int
    total: int
