"""/search — the query language (ADR-0016) over HTTP.

``q`` accepts the full language: ``kind:project status:active tag:oss
confidence>0.8 dark mode``. There are no separate filter params — filters are
operators inside the query, so CLI, REST, and MCP speak identical strings.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, Query

from engram_api.dependencies import get_search_queries
from engram_api.schemas.common import PROBLEM_RESPONSES
from engram_api.schemas.search import SearchHitResponse, SearchResponse
from engram_core.application.queries.search_queries import SearchQueryService

router = APIRouter(prefix="/search", tags=["search"], responses=PROBLEM_RESPONSES)


@router.get("", response_model=SearchResponse)
async def search(
    queries: Annotated[SearchQueryService, Depends(get_search_queries)],
    q: Annotated[str, Query(min_length=1, description="engram query language")],
    cursor: Annotated[str | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
) -> SearchResponse:
    """One language everywhere; FTS is one operator, vectors join it in M5."""
    page = queries.query(q, cursor=cursor, limit=limit)
    return SearchResponse(
        query=q,
        hits=[
            SearchHitResponse(
                memory_id=hit.memory.id,
                kind=hit.memory.kind.value,
                slug=hit.memory.slug,
                title=hit.memory.title,
                snippet=hit.snippet,
                score=hit.score,
                effective_confidence=hit.memory.effective_confidence,
            )
            for hit in page.items
        ],
        next_cursor=page.next_cursor,
    )
