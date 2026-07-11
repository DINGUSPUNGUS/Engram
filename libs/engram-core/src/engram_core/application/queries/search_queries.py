"""Search read side. Recording accesses (for decay) is the *command* side's job —
callers that want recall to count must also invoke ``record_access``."""

from collections.abc import Sequence

from engram_core.application.dto import SearchHit
from engram_core.domain.ports import SearchIndex
from engram_core.domain.values import MemoryKind


class SearchQueryService:
    """Query the search projection (FTS now, vectors later behind the same port)."""

    def __init__(self, index: SearchIndex) -> None:
        self._index = index

    def search(
        self,
        query: str,
        *,
        kind: MemoryKind | None = None,
        tag: str | None = None,
        limit: int = 20,
    ) -> Sequence[SearchHit]:
        """Ranked search over memories. Stale memories are down-ranked, never
        hidden; visibility is enforced against the caller's principal."""
        raise NotImplementedError
