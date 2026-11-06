# 父 router 统一鉴权；测试点专用 16MiB 上限复用已有接收保护。
from typing import Annotated

from fastapi import APIRouter, Depends, Path, Query, Request, Response

from app.api.deps import get_test_case_service, require_admin
from app.api.v1.admin_problem import ProblemBodyRoute, audit_context
from app.models.user import User
from app.schemas.test_case import CaseCreate, CasePage, CaseResponse, CaseUpdate
from app.services.test_case import TestCaseService


class TestCaseBodyRoute(ProblemBodyRoute):
    body_limit = 16 * 1024 * 1024


router = APIRouter(route_class=TestCaseBodyRoute)
Service = Annotated[TestCaseService, Depends(get_test_case_service)]
Admin = Annotated[User, Depends(require_admin)]
Id = Annotated[int, Path(gt=0, le=18446744073709551615)]


@router.get("/problems/{id}/test-cases", response_model=CasePage)
async def list_cases(
    id: Id,
    service: Service,
    page: Annotated[int, Query(ge=1)] = 1,
    size: Annotated[int, Query(ge=1, le=50)] = 20,
) -> CasePage:
    return await service.list_cases(id, page=page, size=size)


@router.post("/problems/{id}/test-cases", response_model=CaseResponse, status_code=201)
async def create_case(
    id: Id,
    data: CaseCreate,
    request: Request,
    actor: Admin,
    service: Service,
) -> CaseResponse:
    return await service.create_case(id, data, **audit_context(request, actor))


@router.put("/test-cases/{id}", response_model=CaseResponse)
async def update_case(
    id: Id,
    data: CaseUpdate,
    request: Request,
    actor: Admin,
    service: Service,
) -> CaseResponse:
    return await service.update_case(id, data, **audit_context(request, actor))


@router.delete("/test-cases/{id}", status_code=204)
async def delete_case(
    id: Id,
    request: Request,
    actor: Admin,
    service: Service,
) -> Response:
    await service.delete_case(id, **audit_context(request, actor))
    return Response(status_code=204)
