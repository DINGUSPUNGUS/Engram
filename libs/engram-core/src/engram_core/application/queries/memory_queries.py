"""Memory read side: current state and listings from the state projection."""

from engram_core.application.dto import MemoryReadModel, Page
from engram_core.domain.ports import MemoryQuery
from engram_core.domain.values import MemoryId, MemoryKind


class MemoryQueryService:
    """Read-only access to projected memory state."""

    def __init__(self, query: MemoryQuery) -> None:
        self._query = query

    def get_memory(self, memory_id: MemoryId) -> MemoryReadModel:
        """Fetch one memory's current state.

        Raises:
            NotFoundError: unknown or deleted memory.
        """
        return self._query.get(memory_id)

    def list_memories(
        self,
        *,
        kind: MemoryKind | None = None,
        tag: str | None = None,
        include_archived: bool = False,
        include_stale: bool = True,
        cursor: str | None = None,
        limit: int = 50,
    ) -> Page[MemoryReadModel]:
        """Cursor-paginated listing with optional filters. Visibility enforcement
        against the caller's principal arrives with the auth milestone; today every
        caller is the owning user."""
        return self._query.list_memories(
            kind=kind,
            tag=tag,
            include_archived=include_archived,
            include_stale=include_stale,
            cursor=cursor,
            limit=limit,
        )
