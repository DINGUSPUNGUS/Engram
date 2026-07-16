"""Data transfer objects crossing the application boundary.

Read models are shaped by projections (not by aggregates); command inputs carry
already-validated primitives plus domain value objects. API schemas and CLI output
map to/from these — domain aggregates never leave the application layer.
"""

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from engram_core.domain.values import Lifetime, MemoryId, MemoryKind, ProposalId, Visibility


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

    ``effective_confidence``, ``stale``, and ``retention_score`` are *derived* at
    read time from stored signals (ADR-0009); ``attributes`` is the kind-schema
    dict, already validated on write.
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
    allowed_actors: tuple[str, ...]
    pinned: bool
    user_weight: float | None
    access_count: int
    last_accessed_at: datetime | None
    retention_score: float
    archived: bool
    created_by: str
    created_at: datetime
    updated_at: datetime
    version: int


# ---------------------------------------------------------------------------
# The query engine (ADR-0016)
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ConfidenceFilter:
    """Comparison against *effective* (decayed) confidence — derived, never stored."""

    op: str  # ">", ">=", "<", "<="
    value: float


@dataclass(frozen=True, slots=True)
class MemoryQuerySpec:
    """One parsed query: AND of every present term (ADR-0016).

    Produced only by ``query_language.parse_query``; executors translate it to their
    storage. ``archived=None`` means the default (exclude archived); ``True`` means
    only archived. ``attributes`` are kind-schema equality terms (``status:active``).
    ``linked`` is a slug or UUID string, resolved by the executor.
    """

    text: str | None = None
    kind: MemoryKind | None = None
    tags: tuple[str, ...] = ()
    slug: str | None = None
    attributes: tuple[tuple[str, str], ...] = ()
    confidence: ConfidenceFilter | None = None
    updated_after: datetime | None = None
    created_after: datetime | None = None
    has: frozenset[str] = frozenset()
    visibility: Visibility | None = None
    linked: str | None = None
    archived: bool | None = None
    pinned: bool | None = None
    stale: bool | None = None


@dataclass(frozen=True, slots=True)
class QueryHit:
    """One query result. ``snippet``/``score`` are set only when free text matched."""

    memory: MemoryReadModel
    snippet: str | None = None
    score: float | None = None


@dataclass(frozen=True, slots=True)
class MemorySnapshot:
    """A memory exactly as it was after event ``version`` — the time-travel view.

    Reconstructed by folding the stream up to a moment or version; carries no derived
    scores (they are functions of *now*, which is precisely what this view escapes).
    """

    id: MemoryId
    kind: MemoryKind
    slug: str
    title: str
    content: str
    attributes: dict[str, object]
    tags: tuple[str, ...]
    confidence: float
    lifetime_policy: str
    visibility: str
    archived: bool
    deleted: bool
    version: int


@dataclass(frozen=True, slots=True)
class TimelineEntry:
    """One event of a memory's history, for audit/timeline views."""

    event_id: UUID
    event_type: str
    occurred_at: datetime
    actor: str
    stream_seq: int


@dataclass(frozen=True, slots=True)
class ProposalListItem:
    """One row of the review queue (from the proposals projection)."""

    id: ProposalId
    title: str
    status: str
    draft_count: int
    opened_by: str
    review_note: str | None
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class ProposalDetail:
    """One proposal in full — folded from its event stream, drafts included."""

    id: ProposalId
    title: str
    description: str
    status: str
    review_note: str | None
    drafts: tuple[dict[str, object], ...]
    merged_event_ids: tuple[UUID, ...]
    version: int


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
