"""Wire shapes for /memories."""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field

MemoryTypeName = Literal["fact", "preference", "project", "reference", "episodic"]
LinkRelationName = Literal["relates_to", "supersedes", "derived_from", "contradicts"]


class LinkView(BaseModel):
    target_id: UUID
    relation: LinkRelationName


class MemoryResponse(BaseModel):
    id: UUID
    slug: str
    title: str
    content: str
    memory_type: MemoryTypeName
    tags: list[str]
    links: list[LinkView]
    archived: bool
    created_at: datetime
    updated_at: datetime
    version: int = Field(description="Optimistic concurrency token; echo it in edits")


class MemoryListResponse(BaseModel):
    items: list[MemoryResponse]
    next_cursor: str | None = None


class CreateMemoryRequest(BaseModel):
    title: str = Field(min_length=1, max_length=500)
    content: str
    memory_type: MemoryTypeName
    slug: str | None = Field(default=None, description="Derived from title when omitted")
    tags: list[str] = []


class EditMemoryRequest(BaseModel):
    """Sparse edit; omitted fields stay unchanged."""

    expected_version: int = Field(ge=1)
    title: str | None = None
    content: str | None = None
    slug: str | None = None
    memory_type: MemoryTypeName | None = None


class TimelineEntryResponse(BaseModel):
    event_id: UUID
    event_type: str
    occurred_at: datetime
    actor: str
    stream_seq: int


class TimelineResponse(BaseModel):
    memory_id: UUID
    entries: list[TimelineEntryResponse]
