"""/events — the audit feed: the raw log, paged by global_seq. Stub."""

from typing import Annotated

from fastapi import APIRouter, Query

from engram_api.schemas.common import PROBLEM_RESPONSES
from engram_api.schemas.events import EventFeedResponse

router = APIRouter(prefix="/events", tags=["events"], responses=PROBLEM_RESPONSES)


@router.get("", response_model=EventFeedResponse)
async def event_feed(
    after: Annotated[int, Query(ge=0, description="Return events after this global_seq")] = 0,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
) -> EventFeedResponse:
    """Everything that happened, in order. Payloads are omitted here; use the
    memory timeline endpoint for payload-level history of one memory."""
    raise NotImplementedError
