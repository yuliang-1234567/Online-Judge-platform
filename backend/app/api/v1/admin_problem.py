# 管理员父 router 统一鉴权；本子路由只接线题库服务和局部 body 接收保护。
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Path, Query, Request
from fastapi.routing import APIRoute

from app.api.deps import get_problem_service, require_admin
from app.core.http import AppError, error_response
from app.models.user import User
from app.schemas.problem import (
    ProblemCreate,
    ProblemDetail,
    ProblemPage,
    ProblemUpdate,
    TagCreate,
    TagPage,
    TagResponse,
)
from app.services.problem import ProblemService

BODY_LIMIT = 256 * 1024


class _BodyTooLarge(HTTPException):
    pass


class ProblemBodyRoute(APIRoute):
    # 子路由只覆盖限额，复用同一接收计数和统一 413 渲染。
    body_limit = BODY_LIMIT

    def get_route_handler(self):
        handler = super().get_route_handler()

        async def limited(request: Request):
            if request.method not in {"POST", "PUT"}:
                return await handler(request)
            received = 0

            async def receive():
                nonlocal received
                message = await request.receive()
                if message["type"] == "http.request":
                    received += len(message.get("body", b""))
                    if received > self.body_limit:
                        # FastAPI 在 body 解析层将 HTTPException 原样抛出，
                        # 普通异常则转换为 400（fastapi/routing.py 的
                        # except HTTPException: raise / except Exception 分支）。
                        # 保留专用 HTTPException 子类，使超限信号保持 413；
                        # 包装器捕获后统一渲染为 error_response。
                        # 若普通异常绕过解析层才会变成 500，
                        # 本实现不依赖该路径。
                        raise _BodyTooLarge(413)
                return message

            try:
                return await handler(Request(request.scope, receive=receive))
            except _BodyTooLarge:
                return error_response(
                    request.state.request_id,
                    AppError(413, "PAYLOAD_TOO_LARGE", "请求体超过限制"),
                )

        return limited


router = APIRouter(route_class=ProblemBodyRoute)
Service = Annotated[ProblemService, Depends(get_problem_service)]
Admin = Annotated[User, Depends(require_admin)]
Page = Annotated[int, Query(ge=1)]
Size = Annotated[int, Query(ge=1, le=50)]
Id = Annotated[int, Path(gt=0)]


def audit_context(request: Request, actor: User) -> dict:
    return {
        "actor_id": actor.id,
        "request_id": request.state.request_id,
        "ip": request.client.host if request.client else None,
    }


@router.post("/problems", response_model=ProblemDetail, status_code=201)
async def create_problem(
    data: ProblemCreate,
    request: Request,
    actor: Admin,
    service: Service,
) -> ProblemDetail:
    return await service.create_problem(data, **audit_context(request, actor))


@router.get("/problems", response_model=ProblemPage)
async def list_problems(
    service: Service,
    page: Page = 1,
    size: Size = 20,
) -> ProblemPage:
    return await service.list_problems(page=page, size=size)


@router.get("/problems/{id}", response_model=ProblemDetail)
async def get_problem(id: Id, service: Service) -> ProblemDetail:
    return await service.get_problem(id)


@router.put("/problems/{id}", response_model=ProblemDetail)
async def update_problem(
    id: Id,
    data: ProblemUpdate,
    request: Request,
    actor: Admin,
    service: Service,
) -> ProblemDetail:
    return await service.update_problem(id, data, **audit_context(request, actor))


@router.get("/tags", response_model=TagPage)
async def list_tags(
    service: Service,
    page: Page = 1,
    size: Size = 20,
) -> TagPage:
    return await service.list_tags(page=page, size=size)


@router.post("/tags", response_model=TagResponse, status_code=201)
async def create_tag(
    data: TagCreate,
    request: Request,
    actor: Admin,
    service: Service,
) -> TagResponse:
    return await service.create_tag(data, **audit_context(request, actor))
