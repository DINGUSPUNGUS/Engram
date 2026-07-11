"""Memory command service.

The choreography every command follows (ADR-0002):

1. load the aggregate (replay its stream) — or start fresh for ``create``,
2. call the aggregate's ``decide_*`` to validate and produce payloads,
3. wrap payloads in envelopes (event id, stream seq, provenance, clock),
4. append via the repository (optimistic concurrency on ``stream_seq``),
5. publish the appended envelopes on the bus so projections fan out.

Bodies are Phase 0.5 stubs; implementations land in roadmap phase 1.
"""

from engram_core.application.dto import (
    CreateMemoryInput,
    EditMemoryInput,
    UpdateAttributesInput,
)
from engram_core.domain.kinds import KindRegistry
from engram_core.domain.ports import Clock, MemoryRepository
from engram_core.domain.values import (
    EvidenceRef,
    Lifetime,
    LinkRelation,
    MemoryId,
    Visibility,
)
from engram_events import EventBus, Provenance


class MemoryCommandService:
    """All write operations on memories."""

    def __init__(
        self,
        repository: MemoryRepository,
        bus: EventBus,
        clock: Clock,
        kinds: KindRegistry,
    ) -> None:
        self._repository = repository
        self._bus = bus
        self._clock = clock
        self._kinds = kinds

    # -- creation & content ---------------------------------------------------

    def create_memory(self, input: CreateMemoryInput, provenance: Provenance) -> MemoryId:
        """Create a typed memory; returns its immutable id. Attributes are
        validated against the kind schema; ``confidence=None`` applies the source
        prior derived from ``provenance``.

        Raises:
            ValidationError: invalid slug/title/attributes/confidence.
        """
        raise NotImplementedError

    def edit_memory(
        self, memory_id: MemoryId, input: EditMemoryInput, provenance: Provenance
    ) -> None:
        """Apply a sparse narrative edit (title/content/slug).

        Raises:
            NotFoundError: unknown or deleted memory.
            StaleVersionError: ``input.expected_version`` is outdated.
        """
        raise NotImplementedError

    def update_attributes(
        self, memory_id: MemoryId, input: UpdateAttributesInput, provenance: Provenance
    ) -> None:
        """Apply a sparse change to kind-schema fields.

        Raises:
            ValidationError: unknown field or vocabulary violation.
            StaleVersionError: outdated expected_version.
        """
        raise NotImplementedError

    # -- justification spine ---------------------------------------------------

    def confirm_memory(self, memory_id: MemoryId, note: str | None, provenance: Provenance) -> None:
        """Vouch for a memory: raises confidence, resets staleness."""
        raise NotImplementedError

    def contradict_memory(
        self,
        memory_id: MemoryId,
        contradicting_id: MemoryId | None,
        note: str | None,
        provenance: Provenance,
    ) -> None:
        """Dispute a memory: lowers confidence and, when ``contradicting_id`` is
        given, creates the ``contradicts`` edge — one unit of work."""
        raise NotImplementedError

    def add_evidence(
        self, memory_id: MemoryId, evidence: EvidenceRef, provenance: Provenance
    ) -> None:
        """Append supporting evidence (a weak confirmation, per scoring.py)."""
        raise NotImplementedError

    def adjust_importance(
        self,
        memory_id: MemoryId,
        *,
        pinned: bool | None = None,
        user_weight: float | None = None,
        provenance: Provenance,
    ) -> None:
        """Pin/unpin or set the explicit user weight."""
        raise NotImplementedError

    def set_visibility(
        self,
        memory_id: MemoryId,
        visibility: Visibility,
        allowed_actors: tuple[str, ...],
        provenance: Provenance,
    ) -> None:
        """Change who may recall this memory."""
        raise NotImplementedError

    def set_lifetime(self, memory_id: MemoryId, lifetime: Lifetime, provenance: Provenance) -> None:
        """Change the retention policy."""
        raise NotImplementedError

    # -- organization & lifecycle ----------------------------------------------

    def tag_memory(
        self,
        memory_id: MemoryId,
        *,
        add: tuple[str, ...] = (),
        remove: tuple[str, ...] = (),
        provenance: Provenance,
    ) -> None:
        """Add/remove tags."""
        raise NotImplementedError

    def link_memories(
        self,
        source_id: MemoryId,
        target_id: MemoryId,
        relation: LinkRelation,
        provenance: Provenance,
    ) -> None:
        """Create a typed tier-1 edge between two memories.

        Raises:
            NotFoundError: either end is unknown.
            ValidationError: self-link, or relation not allowed for the kind.
        """
        raise NotImplementedError

    def merge_memories(
        self,
        survivor_id: MemoryId,
        source_id: MemoryId,
        merged_content: str,
        provenance: Provenance,
    ) -> None:
        """Entity resolution: merge ``source`` into ``survivor`` (same kind only),
        union alias sets, re-point inbound edges, archive the source — one unit
        of work."""
        raise NotImplementedError

    def archive_memory(
        self, memory_id: MemoryId, reason: str | None, provenance: Provenance
    ) -> None:
        """Archive (soft-hide) a memory."""
        raise NotImplementedError

    def restore_memory(self, memory_id: MemoryId, provenance: Provenance) -> None:
        """Restore an archived memory to active."""
        raise NotImplementedError

    def delete_memory(
        self, memory_id: MemoryId, reason: str | None, provenance: Provenance
    ) -> None:
        """Append the tombstone. Never called by automation (ADR-0011)."""
        raise NotImplementedError

    def undo_last_change(self, memory_id: MemoryId, provenance: Provenance) -> None:
        """Append the compensating event for the stream's most recent change.

        Undo is itself an event — history only ever grows.
        """
        raise NotImplementedError

    def record_access(
        self, memory_id: MemoryId, context: str | None, provenance: Provenance
    ) -> None:
        """Record that a consumer recalled this memory (retention-score input)."""
        raise NotImplementedError
