"""Wire shapes for /proposals (PR-style approvals)."""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field

ProposalStatusName = Literal["draft", "pending", "approved", "rejected", "merged"]


class ProposalResponse(BaseModel):
    id: UUID
    title: str
    description: str
    status: ProposalStatusName
    review_note: str | None = None
    created_at: datetime
    updated_at: datetime


class ProposalListResponse(BaseModel):
    items: list[ProposalResponse]
    next_cursor: str | None = None


class OpenProposalRequest(BaseModel):
    title: str = Field(min_length=1, max_length=500)
    description: str = ""
    proposed_events: list[dict[str, object]] = Field(
        default=[],
        description="Serialized event envelopes this proposal wants to append",
    )


class ReviewRequest(BaseModel):
    note: str | None = None
