"""Data transfer objects crossing the application boundary.

Read models are shaped by projections (not by aggregates); command inputs carry
already-validated primitives. API schemas and CLI output map to/from these — domain
objects never leave the application layer.
"""

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from engram_core.domain.values import MemoryId, MemoryType


@dataclass(frozen=True, slots=True)
class Page[T]:
    """One page of a cursor-paginated result."""

    items: tuple[T, ...]
    next_cursor: str | None = None


@dataclass(frozen=True, slots=True)
class LinkView:
    target_id: UUID
    relation: str


@dataclass(frozen=True, slots=True)
class MemoryReadModel:
    """Current state of one memory, as projected into the state tables."""

    id: MemoryId
    slug: str
    title: str
    content: str
    memory_type: MemoryType
    tags: tuple[str, ...]
    links: tuple[LinkView, ...]
    archived: bool
    created_at: datetime
    updated_at: datetime
    version: int


@dataclass(frozen=True, slots=True)
class SearchHit:
    memory_id: MemoryId
    slug: str
    title: str
    snippet: str
    score: float


@dataclass(frozen=True, slots=True)
class TimelineEntry:
    """One event of a memory's history, for audit/timeline views."""

    event_id: UUID
    event_type: str
    occurred_at: datetime
    actor: str
    stream_seq: int


@dataclass(frozen=True, slots=True)
class CreateMemoryInput:
    title: str
    content: str
    memory_type: MemoryType
    slug: str | None = None
    """Optional; the service derives one from the title when omitted."""
    tags: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class EditMemoryInput:
    """Sparse edit: ``None`` means "leave unchanged". ``expected_version`` is the
    optimistic concurrency token from the read model."""

    expected_version: int
    title: str | None = None
    content: str | None = None
    slug: str | None = None
    memory_type: MemoryType | None = None
