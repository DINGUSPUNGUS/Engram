"""Time travel: reconstruct a memory exactly as it existed at a moment or version.

Falls straight out of event sourcing (ADR-0002): fold the stream, stop early. Built
for developers debugging "how did this memory get this way?" — pair with the timeline.
"""

import dataclasses
from datetime import UTC, datetime

from engram_core.application.dto import MemorySnapshot
from engram_core.domain.errors import ValidationError
from engram_core.domain.memory import Memory
from engram_core.domain.ports import MemoryHistory
from engram_core.domain.values import MemoryId


class HistoryQueryService:
    """Point-in-time reads over the event log."""

    def __init__(self, history: MemoryHistory) -> None:
        self._history = history

    def state_at(
        self,
        memory_id: MemoryId,
        *,
        at: datetime | None = None,
        version: int | None = None,
    ) -> MemorySnapshot:
        """The memory as it was after ``version``, or as of instant ``at``
        (naive datetimes are taken as UTC).

        Raises:
            ValidationError: neither or both of ``at``/``version`` given.
            NotFoundError: unknown memory, or it did not exist yet at that point.
        """
        if (at is None) == (version is None):
            raise ValidationError("time travel needs exactly one of --at or --version")
        if at is not None and at.tzinfo is None:
            at = at.replace(tzinfo=UTC)
        memory = self._history.state_at(memory_id, at=at, version=version)
        return _snapshot(memory)


def _snapshot(memory: Memory) -> MemorySnapshot:
    return MemorySnapshot(
        id=memory.id,
        kind=memory.kind,
        slug=str(memory.slug),
        title=memory.title,
        content=memory.content,
        attributes=dataclasses.asdict(memory.attributes),
        tags=tuple(sorted(memory.tags)),
        confidence=memory.confidence,
        lifetime_policy=memory.lifetime.policy.value,
        visibility=memory.visibility.value,
        archived=memory.archived,
        deleted=memory.deleted,
        version=memory.version,
    )
