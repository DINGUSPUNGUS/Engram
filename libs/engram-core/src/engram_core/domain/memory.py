"""The Memory aggregate: one mechanism for all twelve kinds (ADR-0008).

Event-sourced: state is a pure fold over the stream's events (``fold``/``evolve``),
and commands (``decide_*``) validate invariants — including kind-schema validation
through the KindRegistry — and return the event payloads to append. They never
mutate anything themselves.

All bodies are Phase 0.5 stubs: the signatures, invariants, and docstrings are the
contract; implementations land in roadmap phase 1.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime

from engram_core.domain.kinds import KindAttributes, KindRegistry
from engram_core.domain.values import (
    EvidenceRef,
    ImportanceSignals,
    Lifetime,
    Link,
    MemoryId,
    MemoryKind,
    Slug,
    Visibility,
)
from engram_events import EventEnvelope


@dataclass
class Memory:
    """A single remembered thing, folded from its event stream.

    ``version`` equals the last applied ``stream_seq`` and is the optimistic
    concurrency token. ``kind`` is immutable after creation. Staleness is *derived*
    (effective confidence below the kind threshold) and therefore not a field here —
    it lives in the scoring projection.
    """

    id: MemoryId
    kind: MemoryKind
    slug: Slug
    title: str
    content: str
    attributes: KindAttributes
    importance: ImportanceSignals
    confidence: float
    lifetime: Lifetime
    visibility: Visibility
    allowed_actors: tuple[str, ...] = ()
    last_confirmed_at: datetime | None = None
    evidence: tuple[EvidenceRef, ...] = ()
    tags: frozenset[str] = frozenset()
    links: tuple[Link, ...] = ()
    archived: bool = False
    deleted: bool = False
    version: int = 0

    # -- reconstruction (fold) ------------------------------------------------

    @classmethod
    def fold(cls, envelopes: Sequence[EventEnvelope], kinds: KindRegistry) -> "Memory":
        """Rebuild current state by applying every envelope of one stream in order.

        The first envelope must be a ``MemoryCreated``; its attributes dict is
        parsed through the KindRegistry (upcasting historical schema versions).

        Raises:
            ValidationError: empty/malformed stream or unparseable attributes.
        """
        raise NotImplementedError

    def evolve(self, envelope: EventEnvelope) -> "Memory":
        """Return the state after one more event. Pure — total over all registered
        memory event types."""
        raise NotImplementedError

    # -- commands (decide) ----------------------------------------------------
    # Each returns the payload(s) to append; the application layer wraps them in
    # envelopes (ids, seq, provenance, clock) and hands them to the repository.

    @staticmethod
    def decide_create(
        memory_id: MemoryId,
        kind: MemoryKind,
        slug: Slug,
        title: str,
        content: str,
        attributes: KindAttributes,
        kinds: KindRegistry,
        *,
        tags: Sequence[str] = (),
        confidence: float | None = None,
        lifetime: Lifetime | None = None,
        visibility: Visibility | None = None,
    ) -> Sequence[object]:
        """Validate (title, tags, attributes against the kind schema, confidence
        range) and produce ``MemoryCreated``. ``confidence=None`` applies the
        source prior from scoring.py.

        Raises:
            ValidationError: schema mismatch, empty title, bad confidence…
        """
        raise NotImplementedError

    def decide_edit(
        self,
        *,
        title: str | None = None,
        content: str | None = None,
        slug: Slug | None = None,
    ) -> Sequence[object]:
        """Produce ``MemoryEdited`` for changed narrative fields (no-op edits emit
        nothing). ``kind`` is immutable — misclassification is fixed by supersede.

        Raises:
            ConflictError: if the memory is deleted or archived.
        """
        raise NotImplementedError

    def decide_update_attributes(
        self, changes: dict[str, object], kinds: KindRegistry
    ) -> Sequence[object]:
        """Produce ``MemoryAttributesUpdated`` after validating that the merged
        attributes still satisfy the kind schema.

        Raises:
            ValidationError: unknown field or vocabulary violation.
            ConflictError: deleted/archived memory.
        """
        raise NotImplementedError

    # -- spine commands (memory-model.md §3, §5) -------------------------------

    def decide_confirm(self, note: str | None = None) -> Sequence[object]:
        """Produce ``MemoryConfirmed``. Confidence math happens at fold time using
        the confirmer's weight from provenance (scoring.py constants)."""
        raise NotImplementedError

    def decide_contradict(
        self, contradicting_id: MemoryId | None = None, note: str | None = None
    ) -> Sequence[object]:
        """Produce ``MemoryContradicted`` (and the caller links ``contradicts``).

        Raises:
            ValidationError: a memory cannot contradict itself.
        """
        raise NotImplementedError

    def decide_add_evidence(self, evidence: EvidenceRef) -> Sequence[object]:
        """Produce ``MemoryEvidenceAdded``. Evidence is append-only."""
        raise NotImplementedError

    def decide_adjust_importance(
        self, *, pinned: bool | None = None, user_weight: float | None = None
    ) -> Sequence[object]:
        """Produce ``MemoryImportanceAdjusted`` (pin/unpin, explicit weight)."""
        raise NotImplementedError

    def decide_set_visibility(
        self, visibility: Visibility, allowed_actors: Sequence[str] = ()
    ) -> Sequence[object]:
        """Produce ``MemoryVisibilityChanged``.

        Raises:
            ValidationError: RESTRICTED requires a non-empty allow-list; others
                forbid one.
        """
        raise NotImplementedError

    def decide_set_lifetime(self, lifetime: Lifetime) -> Sequence[object]:
        """Produce ``MemoryLifetimeChanged``."""
        raise NotImplementedError

    # -- organization & lifecycle ----------------------------------------------

    def decide_tag(self, add: Sequence[str] = (), remove: Sequence[str] = ()) -> Sequence[object]:
        """Produce ``MemoryTagged`` after normalizing and de-duplicating tags."""
        raise NotImplementedError

    def decide_link(self, link: Link) -> Sequence[object]:
        """Produce ``MemoryLinked``.

        Raises:
            ValidationError: self-link, or the relation is not allowed for this
                kind (memory-model.md §6).
            ConflictError: identical link already exists.
        """
        raise NotImplementedError

    def decide_merge_from(self, source: "Memory", merged_content: str) -> Sequence[object]:
        """Produce ``MemoryMerged`` on this (surviving) memory: alias sets union,
        the application service re-points edges and archives the source.

        Raises:
            ValidationError: kind mismatch — only same-kind memories merge.
        """
        raise NotImplementedError

    def decide_archive(self, reason: str | None = None) -> Sequence[object]:
        """Produce ``MemoryArchived``."""
        raise NotImplementedError

    def decide_restore(self) -> Sequence[object]:
        """Produce ``MemoryRestored``.

        Raises:
            ConflictError: unless currently archived.
        """
        raise NotImplementedError

    def decide_delete(self, reason: str | None = None) -> Sequence[object]:
        """Produce the ``MemoryDeleted`` tombstone. Never called by automation
        (ADR-0011)."""
        raise NotImplementedError

    def decide_record_access(self, context: str | None = None) -> Sequence[object]:
        """Produce ``MemoryAccessed`` (retention-score input)."""
        raise NotImplementedError
