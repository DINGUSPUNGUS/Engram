"""Timeline/audit read side: event history as a first-class view."""

from collections.abc import Sequence

from engram_core.application.dto import TimelineEntry
from engram_core.domain.ports import MemoryQuery
from engram_core.domain.values import MemoryId


class TimelineQueryService:
    """History views derived from the event log."""

    def __init__(self, query: MemoryQuery) -> None:
        self._query = query

    def memory_timeline(self, memory_id: MemoryId) -> Sequence[TimelineEntry]:
        """Full ordered history of one memory.

        Raises:
            NotFoundError: unknown memory.
        """
        return self._query.timeline(memory_id)
