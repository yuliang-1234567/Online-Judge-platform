# 路由通过 Depends 进入此处：组装服务，或按 token 身份、当前账号状态、角色逐层鉴权。
from typing import Annotated

from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.exc import OperationalError
from sqlalchemy.exc import TimeoutError as SQLAlchemyTimeoutError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_session
from app.core.http import AppError
from app.core.security import InvalidAccessToken, decode_access_token
from app.models.user import User
from app.repositories.audit_log import AuditLogRepository
from app.repositories.problem import ProblemRepository, TagRepository
from app.repositories.test_case import TestCaseRepository
from app.repositories.user import UserRepository
from app.services.admin import AdminService
from app.services.auth import AuthService
from app.services.problem import ProblemService
from app.services.problem_publication import ProblemPublicationService
from app.services.test_case import TestCaseService

# Annotated 保留类型信息，Depends 指定实际提供者；
# FastAPI 每请求解析依赖并管理 yield 清理。
# 服务和仓储复用该请求的 session，不能把它提升成跨请求共享对象。
Session = Annotated[AsyncSession, Depends(get_session)]
# 不让安全组件直接返回默认错误；缺失/错误认证方案交由项目统一生成 401 契约。
bearer = HTTPBearer(auto_error=False)


# 只注入已在 lifespan 准备的共享资源；这里不重新创建密码池，也不提前开启事务。
def get_auth_service(request: Request, session: Session) -> AuthService:
    return AuthService(
        session,
        UserRepository(session),
        request.app.state.passwords,
        request.app.state.rate_limiter,
        request.app.state.settings,
    )


# 与鉴权共用请求级 session；服务自行开启业务事务，依赖不提前 begin。
def get_admin_service(session: Session) -> AdminService:
    return AdminService(session, UserRepository(session), AuditLogRepository(session))


# 题目与标签仓储同样共享请求级会话；认证事务结束后由业务服务另开事务。
def get_problem_service(session: Session) -> ProblemService:
    return ProblemService(
        session,
        ProblemRepository(session),
        TagRepository(session),
        AuditLogRepository(session),
    )


# 测试点与题目仓储共享同一会话；不提前开启事务，也不读部署配置。
def get_test_case_service(session: Session) -> TestCaseService:
    return TestCaseService(
        session,
        ProblemRepository(session),
        TestCaseRepository(session),
        AuditLogRepository(session),
    )


def get_problem_publication_service(session: Session) -> ProblemPublicationService:
    return ProblemPublicationService(
        session,
        ProblemRepository(session),
        TagRepository(session),
        TestCaseRepository(session),
        AuditLogRepository(session),
    )


# 第一步验证 token 的签名/类型/时效；第二步查询当前用户，删号为 401、禁用为 403。
# JWT 合法不等于当前仍有权限；每请求新会话避免身份映射缓存拖延禁用/降权生效。
async def get_current_user(
    request: Request,
    session: Session,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)],
) -> User:
    if credentials is None:
        raise AppError(401, "UNAUTHENTICATED", "未登录或凭据无效")
    try:
        claims = decode_access_token(
            credentials.credentials, settings=request.app.state.settings
        )
    except InvalidAccessToken:
        raise AppError(401, "UNAUTHENTICATED", "未登录或凭据无效") from None
    try:
        # JWT 不保存角色/状态；每次请求读库，旧 token 不能绕过后续禁用或降权。
        async with session.begin():
            user = await UserRepository(session).by_id(claims.user_id)
    # 与登录/注册保持同一依赖故障口径；池超时不等于身份或凭据无效。
    except (OperationalError, SQLAlchemyTimeoutError):
        raise AppError(503, "SERVICE_UNAVAILABLE", "认证服务暂时不可用") from None
    if user is None:
        raise AppError(401, "UNAUTHENTICATED", "未登录或凭据无效")
    if user.status != "ACTIVE":
        raise AppError(403, "FORBIDDEN", "账号已禁用")
    return user


# Depends 先执行当前身份与状态检查，再读本次查询的 role；普通用户是 403 而非 401。
# 独立依赖便于管理接口复用，不能只相信前端显示或旧 token 中的角色。
async def require_admin(
    user: Annotated[User, Depends(get_current_user)],
) -> User:
    if user.role != "ADMIN":
        raise AppError(403, "FORBIDDEN", "权限不足")
    return user
