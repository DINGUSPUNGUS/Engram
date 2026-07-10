"""Domain event payloads — the vocabulary of everything that can happen in engram.

Rules (ADR-0002):
- Payloads are frozen dataclasses with JSON-compatible-ish fields (UUIDs and
  datetimes are encoded/decoded by the event store adapter).
- A shipped payload shape is never changed in place. Evolve by bumping the
  ``schema_version`` in :func:`build_registry` and registering an upcaster so
  historical logs replay forever.
- Naming: ``<Noun><PastTenseVerb>`` — events are facts, not commands.
"""

from dataclasses import dataclass, field
from uuid import UUID

from engram_events import EventRegistry

# ---------------------------------------------------------------------------
# Memory events
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class MemoryCreated:
    memory_id: UUID
    slug: str
    title: str
    content: str
    memory_type: str
    tags: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class MemoryEdited:
    """A content-level change. ``None`` means "unchanged"."""

    title: str | None = None
    content: str | None = None
    slug: str | None = None
    memory_type: str | None = None


@dataclass(frozen=True, slots=True)
class MemoryEditedExternally:
    """An edit made directly to the exported markdown, detected by the reconciler."""

    title: str | None = None
    content: str | None = None
    source_path: str = ""


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
    """``source_id`` was merged into this memory (the survivor's stream)."""

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
    """Tombstone. The stream stays in the log (append-only) but state hides it."""

    reason: str | None = None


@dataclass(frozen=True, slots=True)
class MemoryAccessed:
    """A consumer recalled this memory. Feeds future decay/salience scoring."""

    context: str | None = None


# ---------------------------------------------------------------------------
# Proposal events (PR-style approvals)
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
    """Approval was executed: the proposed events were appended to their streams."""

    appended_event_ids: tuple[UUID, ...] = ()


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

_EVENT_TYPES: dict[str, type] = {
    "MemoryCreated": MemoryCreated,
    "MemoryEdited": MemoryEdited,
    "MemoryEditedExternally": MemoryEditedExternally,
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
}


def build_registry() -> EventRegistry:
    """Build the canonical event registry. All payloads start at schema_version 1."""
    registry = EventRegistry()
    for event_type, payload_type in _EVENT_TYPES.items():
        registry.register(event_type, payload_type, schema_version=1)
    return registry
