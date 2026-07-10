"""Memory command service.

The choreography every command follows (ADR-0002):

1. load the aggregate (replay its stream) — or start fresh for ``create``,
2. call the aggregate's ``decide_*`` to validate and produce payloads,
3. wrap payloads in envelopes (event id, stream seq, provenance, clock),
4. append via the repository (optimistic concurrency on ``stream_seq``),
5. publish the appended envelopes on the bus so projections fan out.

Bodies are architecture-phase stubs.
"""

from engram_core.application.dto import CreateMemoryInput, EditMemoryInput
from engram_core.domain.ports import Clock, MemoryRepository
from engram_core.domain.values import LinkRelation, MemoryId
from engram_events import EventBus, Provenance


class MemoryCommandService:
    """All write operations on memories."""

    def __init__(self, repository: MemoryRepository, bus: EventBus, clock: Clock) -> None:
        self._repository = repository
        self._bus = bus
        self._clock = clock

    def create_memory(self, input: CreateMemoryInput, provenance: Provenance) -> MemoryId:
        """Create a new memory; returns its immutable id.

        Raises:
            ValidationError: invalid slug/title/type.
        """
        raise NotImplementedError

    def edit_memory(
        self, memory_id: MemoryId, input: EditMemoryInput, provenance: Provenance
    ) -> None:
        """Apply a sparse edit.

        Raises:
            NotFoundError: unknown or deleted memory.
            StaleVersionError: ``input.expected_version`` is outdated.
        """
        raise NotImplementedError

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
        """Create a typed edge between two memories.

        Raises:
            NotFoundError: either end is unknown.
            ValidationError: self-link.
        """
        raise NotImplementedError

    def merge_memories(
        self,
        survivor_id: MemoryId,
        source_id: MemoryId,
        merged_content: str,
        provenance: Provenance,
    ) -> None:
        """Merge ``source`` into ``survivor`` and archive the source — one unit of work."""
        raise NotImplementedError

    def archive_memory(
        self, memory_id: MemoryId, reason: str | None, provenance: Provenance
    ) -> None:
        """Archive (soft-hide) a memory."""
        raise NotImplementedError

    def delete_memory(
        self, memory_id: MemoryId, reason: str | None, provenance: Provenance
    ) -> None:
        """Append the tombstone. The event stream itself is never erased."""
        raise NotImplementedError

    def undo_last_change(self, memory_id: MemoryId, provenance: Provenance) -> None:
        """Append the compensating event for the stream's most recent change.

        Undo is itself an event — history only ever grows.
        """
        raise NotImplementedError

    def record_access(
        self, memory_id: MemoryId, context: str | None, provenance: Provenance
    ) -> None:
        """Record that a consumer recalled this memory (salience input)."""
        raise NotImplementedError
