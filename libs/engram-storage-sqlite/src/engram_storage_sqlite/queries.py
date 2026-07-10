"""Read-side adapter: implements the ``MemoryQuery`` port over projection tables. Stubs."""

from collections.abc import Sequence

from sqlalchemy.engine import Engine

from engram_core.application.dto import MemoryReadModel, Page, TimelineEntry
from engram_core.domain.values import MemoryId, MemoryType


class SqliteMemoryQuery:
    """Queries ``memories``/``memory_tags``/``links`` and, for timelines, ``events``."""

    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    def get(self, memory_id: MemoryId) -> MemoryReadModel:
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
        raise NotImplementedError

    def timeline(self, memory_id: MemoryId) -> Sequence[TimelineEntry]:
        raise NotImplementedError
