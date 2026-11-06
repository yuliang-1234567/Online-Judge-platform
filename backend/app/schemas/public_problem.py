from typing import Literal

from pydantic import BaseModel, ConfigDict

Difficulty = Literal["EASY", "MEDIUM", "HARD"]


class PublicTag(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str


class PublicProblemSummary(BaseModel):
    id: int
    slug: str
    title: str
    difficulty: Difficulty
    time_limit_ms: int
    memory_limit_mb: int
    tags: list[PublicTag]


class PublicSample(BaseModel):
    case_index: int
    input_data: str
    expected_output: str


class PublicProblemDetail(PublicProblemSummary):
    description: str
    samples: list[PublicSample]


class PublicProblemPage(BaseModel):
    items: list[PublicProblemSummary]
    page: int
    size: int
    total: int
