# 路由交给服务编排限流、密码与仓储；事务在这里收口，仓储只执行数据操作。
import re

from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.exc import TimeoutError as SQLAlchemyTimeoutError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.http import AppError
from app.core.rate_limit import AuthRateLimiter
from app.core.security import (
    PasswordContext,
    create_access_token,
    hash_password,
    verify_dummy_password,
    verify_password,
)
from app.models.user import User
from app.repositories.user import UserRepository
from app.schemas.auth import LoginRequest, RegisterRequest, TokenResponse


# 1062 只表示重复键；还须命中用户名约束，才能把异常解释为用户名重复并返回 409。
# 其他唯一键或完整性错误继续暴露为内部故障，不能用宽泛匹配掩盖结构/程序错误。
def _username_conflict(error: IntegrityError) -> bool:
    args = getattr(error.orig, "args", ())
    return (
        len(args) >= 2
        and args[0] == 1062
        and re.search(r"for key ['`](?:users\.)?uk_users_username['`]", str(args[1]))
        is not None
    )


# get_auth_service 每请求组装服务；
# get_session 创建并最终关闭会话，服务不拥有其生命周期。
# 同一请求内仓储和服务使用同一 session；密码池与限流器则从应用实例共享。
class AuthService:
    def __init__(
        self,
        session: AsyncSession,
        users: UserRepository,
        passwords: PasswordContext,
        limiter: AuthRateLimiter,
        settings: Settings,
    ) -> None:
        self.session = session
        self.users = users
        self.passwords = passwords
        self.limiter = limiter
        self.settings = settings

    # 先限流再哈希，避免已超限请求占 CPU；begin 成功退出才提交，return 不会提前报成功。
    async def register(self, data: RegisterRequest, ip: str) -> User:
        await self.limiter.check_registration(ip)
        encoded = await hash_password(data.password, ctx=self.passwords)
        try:
            # CPU 工作在事务外；flush/refresh/commit 任一步失败都由 begin 上下文回滚。
            # 先查再写不能防并发重名，最终以唯一约束冲突为准，其他约束错误不得冒充 409。
            async with self.session.begin():
                user = await self.users.create(data.username, encoded)
        except IntegrityError as error:
            if _username_conflict(error):
                raise AppError(409, "CONFLICT", "用户名已存在") from None
            raise
        # 池暂时借不到连接也是依赖不可用；程序错误不能一并伪装为可重试的 503。
        except (OperationalError, SQLAlchemyTimeoutError):
            raise AppError(503, "SERVICE_UNAVAILABLE", "认证服务暂时不可用") from None
        return user

    # 只为读取用户短暂持有事务，耗时校验在事务外；本次读取不替代下一请求重新鉴权。
    async def login(self, data: LoginRequest, ip: str) -> TokenResponse:
        await self.limiter.check_login(ip, data.username)
        try:
            # 读事务先结束，避免慢哈希占用连接；下一次鉴权仍重新读账号状态。
            async with self.session.begin():
                user = await self.users.by_username(data.username)
        except (OperationalError, SQLAlchemyTimeoutError):
            raise AppError(503, "SERVICE_UNAVAILABLE", "认证服务暂时不可用") from None
        # 缺账号也做同池 dummy，但强制 matched=False；耗时补偿绝不是身份证明。
        if user is None:
            await verify_dummy_password(data.password, ctx=self.passwords)
            matched = False
        else:
            matched = await verify_password(
                data.password, user.password_hash, ctx=self.passwords
            )
        if not matched:
            await self.limiter.record_login_failure(ip, data.username)
            raise AppError(401, "UNAUTHENTICATED", "用户名或密码错误")
        # 先验密码再暴露禁用状态，否则仅凭用户名就能用 401/403 差异探测账号。
        if user.status != "ACTIVE":
            raise AppError(403, "FORBIDDEN", "账号已禁用")
        # token 使用当前已验证的用户 ID；
        # expires_in 按秒返回，与签发端的分钟换算保持一致。
        return TokenResponse(
            access_token=create_access_token(user.id, settings=self.settings),
            expires_in=self.settings.jwt_expire_minutes * 60,
        )
