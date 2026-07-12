"""Wire shapes for /search (the query language, ADR-0016)."""

from uuid import UUID

from pydantic import BaseModel


class SearchHitResponse(BaseModel):
    memory_id: UUID
    kind: str
    slug: str
    title: str
    snippet: str | None = None
    score: float | None = None
    effective_confidence: float


class SearchResponse(BaseModel):
    query: str
    hits: list[SearchHitResponse]
    next_cursor: str | None = None
