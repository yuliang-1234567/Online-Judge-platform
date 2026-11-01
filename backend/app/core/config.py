import re
from urllib.parse import urlsplit

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import make_url
from sqlalchemy.exc import ArgumentError


# lifespan 构造并校验配置，模块导入不读取环境；校验只查格式，不连接 MySQL/Redis。
# SecretStr 只是显示遮蔽，不是加密；仅在使用点解包，禁止配置转储或记录原值。
class Settings(BaseSettings):
    # 配置错误不能把包含凭据的输入写入异常；真实 .env 由启动入口显式加载。
    model_config = SettingsConfigDict(extra="ignore", hide_input_in_errors=True)

    database_url: SecretStr
    redis_url: SecretStr
    jwt_secret: SecretStr
    jwt_expire_minutes: int = Field(default=60, ge=30, le=60)
    rate_limit_key_prefix: str = "oj:ratelimit:auth"

    # 下限是 UTF-8 字节数而非字符数；长度门槛不等于随机性保证，仍须使用随机生成的密钥。
    @field_validator("jwt_secret")
    @classmethod
    def validate_jwt_secret(cls, value: SecretStr) -> SecretStr:
        if len(value.get_secret_value().encode("utf-8")) < 32:
            raise ValueError("JWT 密钥至少需要 32 字节")
        return value

    @field_validator("database_url")
    @classmethod
    def validate_database_url(cls, value: SecretStr) -> SecretStr:
        try:
            url = make_url(value.get_secret_value())
            valid = url.drivername == "mysql+asyncmy" and url.host and url.database
        except (ArgumentError, ValueError, TypeError):
            # URL 解析异常可能带原始连接串，统一替换为不含输入的配置错误。
            valid = False
        if not valid:
            raise ValueError("DATABASE_URL 必须为 mysql+asyncmy 连接串") from None
        return value

    @field_validator("redis_url")
    @classmethod
    def validate_redis_url(cls, value: SecretStr) -> SecretStr:
        try:
            url = urlsplit(value.get_secret_value())
            valid = url.scheme in {"redis", "rediss"} and bool(url.hostname)
            valid = valid and (not url.path or url.path[1:].isdigit())
            if url.port is not None:
                valid = valid and 0 < url.port < 65536
        except ValueError:
            valid = False
        if not valid:
            raise ValueError("REDIS_URL 必须为 redis 或 rediss 连接串") from None
        return value

    # 前缀划开运行环境/测试的键空间；拒绝尾随冒号，避免拼接时出现意外的双分隔符。
    @field_validator("rate_limit_key_prefix")
    @classmethod
    def validate_prefix(cls, value: str) -> str:
        if not re.fullmatch(r"[A-Za-z0-9:_-]{1,128}", value) or value.endswith(":"):
            raise ValueError("限流前缀格式不合法")
        return value
