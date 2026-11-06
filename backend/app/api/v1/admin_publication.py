from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Path, Request
from pydantic import BaseModel

from app.api.deps import get_problem_publication_service, require_admin
from app.api.v1.admin_problem import audit_context
from app.models.user import User
from app.services.problem_publication import ProblemPublicationService


class PublicationResponse(BaseModel):
    id: int
    status: Literal["PUBLISHED", "OFFLINE"]


router = APIRouter()
Service = Annotated[ProblemPublicationService, Depends(get_problem_publication_service)]
Admin = Annotated[User, Depends(require_admin)]
Id = Annotated[int, Path(gt=0, le=18_446_744_073_709_551_615)]


@router.post("/problems/{id}/publish", response_model=PublicationResponse)
async def publish_problem(
    id: Id, request: Request, actor: Admin, service: Service
) -> dict:
    return await service.transition(id, "PUBLISHED", **audit_context(request, actor))


@router.post("/problems/{id}/offline", response_model=PublicationResponse)
async def offline_problem(
    id: Id, request: Request, actor: Admin, service: Service
) -> dict:
    return await service.transition(id, "OFFLINE", **audit_context(request, actor))
