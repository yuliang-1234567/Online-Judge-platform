# 路由先用请求模型限制输入，再进入服务；
# 响应模型另设字段白名单，不能直接序列化 ORM 全字段。
import re
from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_serializer, field_validator


# Field 先检查严格字符串类型与长度，
# 默认 after validator 再检查业务格式；失败不进入路由。
# 长度按 Unicode 码点而非 UTF-8 字节/视觉字符；不 trim、不规范化，密码原值必须保留。
class LoginRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=False)

    username: str = Field(strict=True, min_length=3, max_length=32)
    # repr=False 只遮住对象表示，校验错误仍可能含 input；422 脱敏由 HTTP 处理器负责。
    password: str = Field(strict=True, min_length=1, max_length=128, repr=False)

    # fullmatch 限制 ASCII 格式并拒绝尾随换行；用户名长度通过不等于字符集合合法。
    @field_validator("username")
    @classmethod
    def validate_username(cls, value: str) -> str:
        if re.fullmatch(r"[A-Za-z0-9_]{3,32}", value) is None:
            raise ValueError("用户名格式不合法")
        return value


class RegisterRequest(LoginRequest):
    # 注册限制新凭据；登录不复用最小长度，避免未来政策变化锁死旧用户。
    password: str = Field(strict=True, min_length=15, max_length=128, repr=False)

    # 继承用户名校验但单独限制新密码；仅拒绝全空白，不删除合法密码两端的空白。
    @field_validator("password")
    @classmethod
    def reject_blank_password(cls, value: str) -> str:
        if value.isspace():
            raise ValueError("密码不能全为空白")
        return value


# from_attributes 从 ORM 读取此处声明的字段；
# 白名单没有 password_hash，因此不向外返回它。
# Literal 限定对外状态/角色，映射不符合契约时不能悄悄输出新值。
class UserResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    username: str
    role: Literal["USER", "ADMIN"]
    status: Literal["ACTIVE", "DISABLED"]
    created_at: datetime

    @field_serializer("created_at")
    def serialize_created_at(self, value: datetime) -> str:
        # MySQL DATETIME 不携带时区；连接已固定 UTC，响应统一成毫秒 UTC 文本。
        if value.tzinfo is None:
            value = value.replace(tzinfo=UTC)
        return (
            value.astimezone(UTC)
            .isoformat(timespec="milliseconds")
            .replace("+00:00", "Z")
        )


# token 是有意返回给登录者的凭据，repr=False 不禁止 JSON 输出；expires_in 的单位是秒。
class TokenResponse(BaseModel):
    access_token: str = Field(repr=False)
    token_type: Literal["bearer"] = "bearer"
    expires_in: int
