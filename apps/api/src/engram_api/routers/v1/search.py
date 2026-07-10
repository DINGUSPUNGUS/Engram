"""/search — ranked search over the search projection. Architecture-phase stub."""

from typing import Annotated

from fastapi import APIRouter, Depends, Query

from engram_api.dependencies import get_search_queries
from engram_api.schemas.common import PROBLEM_RESPONSES
from engram_api.schemas.memories import MemoryTypeName
from engram_api.schemas.search import SearchResponse
from engram_core.application.queries.search_queries import SearchQueryService

router = APIRouter(prefix="/search", tags=["search"], responses=PROBLEM_RESPONSES)


@router.get("", response_model=SearchResponse)
async def search(
    queries: Annotated[SearchQueryService, Depends(get_search_queries)],
    q: Annotated[str, Query(min_length=1)],
    memory_type: Annotated[MemoryTypeName | None, Query()] = None,
    tag: Annotated[str | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
) -> SearchResponse:
    """FTS today, hybrid vector+FTS later — same endpoint, same shape."""
    raise NotImplementedError
