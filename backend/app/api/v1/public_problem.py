from typing import Annotated

from fastapi import APIRouter, Depends, Path, Query, Request

from app.api.deps import get_problem_publication_service
from app.core.http import AppError
from app.schemas.public_problem import (
    Difficulty,
    PublicProblemDetail,
    PublicProblemPage,
)
from app.services.problem_publication import ProblemPublicationService

router = APIRouter(prefix="/api/v1/problems", tags=["problems"])
Service = Annotated[ProblemPublicationService, Depends(get_problem_publication_service)]


@router.get("", response_model=PublicProblemPage)
async def list_problems(
    request: Request,
    service: Service,
    page: Annotated[int, Query(ge=1)] = 1,
    size: Annotated[int, Query(ge=1, le=50)] = 20,
    difficulty: Difficulty | None = None,
    tag_id: Annotated[int | None, Query(gt=0, le=18_446_744_073_709_551_615)] = None,
    q: Annotated[str | None, Query(max_length=128)] = None,
) -> PublicProblemPage:
    if len(request.query_params.getlist("tag_id")) > 1:
        raise AppError(422, "VALIDATION_ERROR", "只允许一个 tag_id")
    return await service.list_public(
        page=page, size=size, difficulty=difficulty, tag_id=tag_id, q=q
    )


@router.get("/{id}", response_model=PublicProblemDetail)
async def get_problem(
    id: Annotated[int, Path(gt=0, le=18_446_744_073_709_551_615)], service: Service
) -> PublicProblemDetail:
    return await service.get_public(id)
