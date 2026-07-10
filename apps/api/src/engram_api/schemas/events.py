"""Wire shapes for the /events audit feed."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel


class EventResponse(BaseModel):
    global_seq: int
    event_id: UUID
    stream_id: UUID
    stream_seq: int
    event_type: str
    occurred_at: datetime
    actor: str


class EventFeedResponse(BaseModel):
    items: list[EventResponse]
    next_after: int | None = None
