from typing import Annotated

from fastapi import APIRouter, Depends, Path, Query, Request

from app.api.deps import get_admin_service, require_admin
from app.api.v1.admin_problem import router as problem_router
from app.api.v1.admin_test_case import router as test_case_router
from app.models.user import User
from app.schemas.admin import AuditLogPage, UserPage, UserPatch
from app.schemas.auth import UserResponse
from app.services.admin import AdminService

# 路由统一鉴权；PATCH 的操作者参数复用同一依赖的请求内缓存，不复制角色分支。
router = APIRouter(
    prefix="/api/v1/admin", tags=["admin"], dependencies=[Depends(require_admin)]
)
Service = Annotated[AdminService, Depends(get_admin_service)]
Admin = Annotated[User, Depends(require_admin)]


@router.get("/users", response_model=UserPage)
async def list_users(
    service: Service,
    page: Annotated[int, Query(ge=1)] = 1,
    size: Annotated[int, Query(ge=1, le=50)] = 20,
    username: Annotated[str | None, Query(max_length=32)] = None,
) -> UserPage:
    return await service.list_users(page=page, size=size, username=username)


@router.patch("/users/{id}", response_model=UserResponse)
async def patch_user(
    id: Annotated[int, Path(gt=0)],
    data: UserPatch,
    request: Request,
    actor: Admin,
    service: Service,
) -> UserResponse:
    return await service.patch_user(
        id,
        data,
        actor_id=actor.id,
        request_id=request.state.request_id,
        ip=request.client.host if request.client else None,
    )


@router.get("/audit-logs", response_model=AuditLogPage)
async def list_audits(
    service: Service,
    cursor: Annotated[int | None, Query(gt=0)] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
) -> AuditLogPage:
    return await service.list_audits(cursor=cursor, limit=limit)


# 子路由沿用本 router 的权限依赖与 /api/v1/admin 前缀。
router.include_router(problem_router)
router.include_router(test_case_router)
