"""Wire shapes for /proposals (PR-style approvals)."""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field

from engram_api.schemas.common import ProvenanceView

ProposalStatusName = Literal["draft", "pending", "approved", "rejected", "merged", "undone"]


class ProposalResponse(BaseModel):
    """One row of the review queue.

    Deliberately not a truncated detail view: the queue projection knows how many
    drafts a proposal carries and who opened it, but not the drafts themselves.
    Fetch ``/proposals/{id}`` for those rather than inferring them here.
    """

    id: UUID
    title: str
    status: ProposalStatusName
    review_note: str | None = None
    draft_count: int
    opened_by: str
    created_at: datetime
    updated_at: datetime


class ProposalListResponse(BaseModel):
    items: list[ProposalResponse]
    next_cursor: str | None = None


class ProposalDetailResponse(BaseModel):
    """One proposal folded from its stream — the reviewer's view.

    ``drafts`` are the intents awaiting review; ``merged_event_ids`` are the events a
    merge actually appended (ADR-0021). Both are read straight off the aggregate: the
    dashboard renders them, it never derives them.
    """

    id: UUID
    title: str
    description: str
    status: ProposalStatusName
    review_note: str | None = None
    drafts: list[dict[str, object]] = Field(default_factory=list)
    merged_event_ids: list[UUID] = Field(default_factory=list)
    version: int


class ProposalTimelineEntryResponse(BaseModel):
    """One event in a proposal's lifecycle, provenance included."""

    event_id: UUID
    event_type: str
    occurred_at: datetime
    stream_seq: int
    provenance: ProvenanceView


class ProposalTimelineResponse(BaseModel):
    proposal_id: UUID
    entries: list[ProposalTimelineEntryResponse]


class OpenProposalRequest(BaseModel):
    title: str = Field(min_length=1, max_length=500)
    description: str = ""
    proposed_events: list[dict[str, object]] = Field(
        default=[],
        description="Serialized event envelopes this proposal wants to append",
    )


class ReviewRequest(BaseModel):
    note: str | None = None


class MergeResponse(BaseModel):
    """What a merge appended — the provenance link from proposal to memory events."""

    proposal: ProposalDetailResponse
    appended_event_ids: list[UUID]


class UndoResponse(BaseModel):
    """What an undo compensated with (ADR-0018 §3: compensation, never erasure)."""

    proposal: ProposalDetailResponse
    compensating_event_ids: list[UUID]
