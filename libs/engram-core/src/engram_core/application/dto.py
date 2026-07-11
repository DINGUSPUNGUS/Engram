"""Data transfer objects crossing the application boundary.

Read models are shaped by projections (not by aggregates); command inputs carry
already-validated primitives plus domain value objects. API schemas and CLI output
map to/from these — domain aggregates never leave the application layer.
"""

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from engram_core.domain.values import Lifetime, MemoryId, MemoryKind, Visibility


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
class EvidenceView:
    evidence_type: str
    value: str
    note: str | None = None
    added_at: datetime | None = None
    actor: str | None = None


@dataclass(frozen=True, slots=True)
class MemoryReadModel:
    """Current state of one memory, as projected — spine included.

    ``effective_confidence`` and ``stale`` are *derived* by the scoring projection
    (ADR-0009); ``attributes`` is the kind-schema dict, already validated on write.
    """

    id: MemoryId
    kind: MemoryKind
    slug: str
    title: str
    content: str
    attributes: dict[str, object]
    tags: tuple[str, ...]
    links: tuple[LinkView, ...]
    evidence: tuple[EvidenceView, ...]
    confidence: float
    effective_confidence: float
    stale: bool
    last_confirmed_at: datetime | None
    lifetime_policy: str
    lifetime_until: datetime | None
    visibility: str
    pinned: bool
    user_weight: float | None
    archived: bool
    created_at: datetime
    updated_at: datetime
    version: int


@dataclass(frozen=True, slots=True)
class SearchHit:
    memory_id: MemoryId
    kind: MemoryKind
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
    kind: MemoryKind
    title: str
    content: str
    attributes: dict[str, object]
    slug: str | None = None
    """Optional; the service derives one from the title when omitted."""
    tags: tuple[str, ...] = ()
    confidence: float | None = None
    """None applies the source prior (scoring.py) based on provenance."""
    lifetime: Lifetime | None = None
    visibility: Visibility | None = None


@dataclass(frozen=True, slots=True)
class EditMemoryInput:
    """Sparse narrative edit: ``None`` means "leave unchanged". ``kind`` is
    immutable; structured fields go through ``UpdateAttributesInput``."""

    expected_version: int
    title: str | None = None
    content: str | None = None
    slug: str | None = None


@dataclass(frozen=True, slots=True)
class UpdateAttributesInput:
    """Sparse change to kind-schema fields, validated against the KindRegistry."""

    expected_version: int
    changes: dict[str, object]
