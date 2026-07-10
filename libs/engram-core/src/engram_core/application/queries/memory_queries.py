"""Memory read side: current state and listings from the state projection."""

from engram_core.application.dto import MemoryReadModel, Page
from engram_core.domain.ports import MemoryQuery
from engram_core.domain.values import MemoryId, MemoryType


class MemoryQueryService:
    """Read-only access to projected memory state."""

    def __init__(self, query: MemoryQuery) -> None:
        self._query = query

    def get_memory(self, memory_id: MemoryId) -> MemoryReadModel:
        """Fetch one memory's current state.

        Raises:
            NotFoundError: unknown or deleted memory.
        """
        raise NotImplementedError

    def list_memories(
        self,
        *,
        memory_type: MemoryType | None = None,
        tag: str | None = None,
        include_archived: bool = False,
        cursor: str | None = None,
        limit: int = 50,
    ) -> Page[MemoryReadModel]:
        """Cursor-paginated listing with optional filters."""
        raise NotImplementedError
