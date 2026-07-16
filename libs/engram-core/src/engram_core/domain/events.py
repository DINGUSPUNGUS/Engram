"""Domain event payloads — the vocabulary of everything that can happen in engram.

Rules (ADR-0002):
- Payloads are frozen dataclasses with JSON-compatible-ish fields (UUIDs and
  datetimes are encoded/decoded by the event store adapter). Kind attributes travel
  as plain dicts in payloads; the aggregate validates them against the KindRegistry
  *before* emitting (ADR-0008).
- A shipped payload shape is never changed in place. Evolve by bumping the
  ``schema_version`` in :func:`build_registry` and registering an upcaster so
  historical logs replay forever.
- Naming: ``<Noun><PastTenseVerb>`` — events are facts, not commands.

The full taxonomy is documented in docs/events.md and docs/memory-model.md §10.
"""

from dataclasses import dataclass, field
from datetime import datetime
from uuid import UUID

from engram_events import EventRegistry

# ---------------------------------------------------------------------------
# Memory events — creation & content
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class MemoryCreated:
    memory_id: UUID
    kind: str
    slug: str
    title: str
    content: str
    attributes: dict[str, object]
    attributes_schema_version: int = 1
    tags: tuple[str, ...] = ()
    confidence: float = 0.6
    lifetime_policy: str = "standard"
    lifetime_until: datetime | None = None
    visibility: str = "shared"


@dataclass(frozen=True, slots=True)
class MemoryEdited:
    """A narrative-level change. ``None`` means "unchanged". ``kind`` is immutable —
    structured fields change via ``MemoryAttributesUpdated``."""

    title: str | None = None
    content: str | None = None
    slug: str | None = None


@dataclass(frozen=True, slots=True)
class MemoryAttributesUpdated:
    """Sparse change to kind-schema fields, validated against the KindRegistry."""

    changes: dict[str, object]
    attributes_schema_version: int = 1


@dataclass(frozen=True, slots=True)
class MemoryEditedExternally:
    """An edit made directly to the exported markdown, detected by the reconciler."""

    title: str | None = None
    content: str | None = None
    source_path: str = ""


# ---------------------------------------------------------------------------
# Memory events — justification spine (memory-model.md §3, §5)
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class MemoryConfirmed:
    """Someone vouched for this memory: raises confidence (c' = c + (1-c)·w),
    resets staleness. ``weight`` is resolved from the scoring policy at decide
    time and recorded here so replay never depends on live config (ADR-0019)."""

    note: str | None = None
    weight: float = 0.40


@dataclass(frozen=True, slots=True)
class MemoryContradicted:
    """Someone disputed this memory: lowers confidence (c' = c·(1-w)); the
    contradicts edge is a companion ``MemoryLinked`` event. ``weight`` is
    resolved at decide time and recorded (ADR-0019)."""

    contradicting_id: UUID | None = None
    note: str | None = None
    weight: float = 0.40


@dataclass(frozen=True, slots=True)
class MemoryConfidenceRestored:
    """Confidence inputs restored to recorded prior values. Emitted ONLY by
    proposal undo when compensating a confirm/contradict (ADR-0019 §2, the
    ``MemoryEvidenceRetracted`` precedent) — no command produces it."""

    confidence: float
    last_confirmed_at: datetime | None = None
    reason: str | None = None


@dataclass(frozen=True, slots=True)
class MemoryEvidenceAdded:
    evidence_type: str
    value: str
    note: str | None = None


@dataclass(frozen=True, slots=True)
class MemoryEvidenceRetracted:
    """Evidence entry ``seq`` (1-based, in add order) no longer counts toward
    current state. The log keeps both the evidence and this retraction —
    append-only as history, reversible as state (ADR-0018). Emitted by undo."""

    seq: int
    reason: str | None = None


@dataclass(frozen=True, slots=True)
class MemoryImportanceAdjusted:
    """Pin/unpin or set an explicit user weight. ``None`` means "unchanged";
    clearing an existing weight back to unset is ``clear_user_weight=True``
    (needed so undo can restore "no weight" — ADR-0019)."""

    pinned: bool | None = None
    user_weight: float | None = None
    clear_user_weight: bool = False


@dataclass(frozen=True, slots=True)
class MemoryVisibilityChanged:
    visibility: str
    allowed_actors: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class MemoryLifetimeChanged:
    lifetime_policy: str
    lifetime_until: datetime | None = None


# ---------------------------------------------------------------------------
# Memory events — organization & lifecycle
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class MemoryTagged:
    added: tuple[str, ...] = ()
    removed: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class MemoryLinked:
    target_id: UUID
    relation: str


@dataclass(frozen=True, slots=True)
class MemoryUnlinked:
    target_id: UUID
    relation: str


@dataclass(frozen=True, slots=True)
class MemoryMerged:
    """``source_id`` was merged into this memory (the survivor's stream).
    Entity resolution lands here: alias sets union, edges re-point."""

    source_id: UUID
    merged_content: str


@dataclass(frozen=True, slots=True)
class MemoryArchived:
    reason: str | None = None


@dataclass(frozen=True, slots=True)
class MemoryRestored:
    pass


@dataclass(frozen=True, slots=True)
class MemoryDeleted:
    """Tombstone. The stream stays in the log (append-only) but state hides it.
    Never automated (ADR-0011)."""

    reason: str | None = None


@dataclass(frozen=True, slots=True)
class MemoryAccessed:
    """A consumer recalled this memory. Feeds retention scoring (ADR-0009)."""

    context: str | None = None


# ---------------------------------------------------------------------------
# Proposal events (PR-style approvals; also the vehicle for pruning, ADR-0011)
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ProposalOpened:
    proposal_id: UUID
    title: str
    description: str = ""
    proposed_events: tuple[dict[str, object], ...] = field(default_factory=tuple)
    """Serialized envelopes this proposal wants to append to target streams."""


@dataclass(frozen=True, slots=True)
class ProposalApproved:
    note: str | None = None


@dataclass(frozen=True, slots=True)
class ProposalRejected:
    note: str | None = None


@dataclass(frozen=True, slots=True)
class ProposalMerged:
    """Approval was executed: the aggregate-decided events were appended to their
    target streams (ADR-0018: drafts are intents; merge is the event producer)."""

    appended_event_ids: tuple[UUID, ...] = ()


@dataclass(frozen=True, slots=True)
class ProposalUndone:
    """The merge was compensated: one inverse event per merged event, appended in
    reverse order (ADR-0018). History is never rewritten."""

    note: str | None = None
    compensating_event_ids: tuple[UUID, ...] = ()


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

_EVENT_TYPES: dict[str, type] = {
    "MemoryCreated": MemoryCreated,
    "MemoryEdited": MemoryEdited,
    "MemoryAttributesUpdated": MemoryAttributesUpdated,
    "MemoryEditedExternally": MemoryEditedExternally,
    "MemoryConfirmed": MemoryConfirmed,
    "MemoryContradicted": MemoryContradicted,
    "MemoryConfidenceRestored": MemoryConfidenceRestored,
    "MemoryEvidenceAdded": MemoryEvidenceAdded,
    "MemoryEvidenceRetracted": MemoryEvidenceRetracted,
    "MemoryImportanceAdjusted": MemoryImportanceAdjusted,
    "MemoryVisibilityChanged": MemoryVisibilityChanged,
    "MemoryLifetimeChanged": MemoryLifetimeChanged,
    "MemoryTagged": MemoryTagged,
    "MemoryLinked": MemoryLinked,
    "MemoryUnlinked": MemoryUnlinked,
    "MemoryMerged": MemoryMerged,
    "MemoryArchived": MemoryArchived,
    "MemoryRestored": MemoryRestored,
    "MemoryDeleted": MemoryDeleted,
    "MemoryAccessed": MemoryAccessed,
    "ProposalOpened": ProposalOpened,
    "ProposalApproved": ProposalApproved,
    "ProposalRejected": ProposalRejected,
    "ProposalMerged": ProposalMerged,
    "ProposalUndone": ProposalUndone,
}


def build_registry() -> EventRegistry:
    """Build the canonical event registry. All payloads start at schema_version 1."""
    registry = EventRegistry()
    for event_type, payload_type in _EVENT_TYPES.items():
        registry.register(event_type, payload_type, schema_version=1)
    return registry
