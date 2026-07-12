"""Query read side: the query language (ADR-0016) over the QueryEngine port.

Recording accesses (for decay) is the *command* side's job — callers that want
recall to count must also invoke ``record_access``.
"""

from engram_core.application.dto import Page, QueryHit
from engram_core.application.queries.query_language import parse_query
from engram_core.domain.kinds import KindRegistry
from engram_core.domain.ports import Clock, QueryEngine


class SearchQueryService:
    """Parses query-language strings and delegates execution. CLI, REST, and MCP
    all come through here — one language, one parser, many executors."""

    def __init__(self, engine: QueryEngine, clock: Clock, kinds: KindRegistry) -> None:
        self._engine = engine
        self._clock = clock
        self._kinds = kinds

    def query(self, query: str, *, cursor: str | None = None, limit: int = 20) -> Page[QueryHit]:
        """Execute one query-language string against the projections.

        Raises:
            ValidationError: the query does not parse.
        """
        spec = parse_query(query, now=self._clock.now(), kinds=self._kinds)
        return self._engine.query(spec, cursor=cursor, limit=limit)
