from typing import Annotated

from fastapi import APIRouter, Depends, Request

from app.api.deps import get_auth_service, get_current_user
from app.models.user import User
from app.schemas.auth import LoginRequest, RegisterRequest, TokenResponse, UserResponse
from app.services.auth import AuthService

# main 挂载路由；此层只接入请求模型、依赖和响应白名单，直接转发无需重复业务分支。
# 限流/密码/事务集中在 service，避免新增入口时遗漏步骤或在响应前提前提交。
router = APIRouter(prefix="/api/v1/auth", tags=["auth"])
Service = Annotated[AuthService, Depends(get_auth_service)]


def _peer_ip(request: Request) -> str:
    # 不直接信任用户可伪造的 X-Forwarded-For；可信代理由服务器入口配置。
    return request.client.host if request.client else "unknown"


@router.post("/register", status_code=201, response_model=UserResponse)
async def register(data: RegisterRequest, request: Request, service: Service) -> User:
    return await service.register(data, _peer_ip(request))


@router.post("/login", response_model=TokenResponse)
async def login(
    data: LoginRequest, request: Request, service: Service
) -> TokenResponse:
    return await service.login(data, _peer_ip(request))


# /me 依赖先查当前身份和状态，响应只放 UserResponse 字段；不从 token 推断账号详情。
@router.get("/me", response_model=UserResponse)
async def me(user: Annotated[User, Depends(get_current_user)]) -> User:
    return user
