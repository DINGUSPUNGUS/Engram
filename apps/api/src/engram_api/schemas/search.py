"""Wire shapes for /search."""

from uuid import UUID

from pydantic import BaseModel


class SearchHitResponse(BaseModel):
    memory_id: UUID
    slug: str
    title: str
    snippet: str
    score: float


class SearchResponse(BaseModel):
    query: str
    hits: list[SearchHitResponse]
