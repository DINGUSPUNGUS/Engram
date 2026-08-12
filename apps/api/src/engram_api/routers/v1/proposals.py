"""/proposals — PR-style review of memory changes.

Every handler parses input, calls one service, and maps the result (ADR-0007). The
review lifecycle lives in ``ProposalCommandService`` and the aggregate; nothing here
decides whether a proposal may be approved, merged, or undone.
"""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, status

from engram_api.dependencies import (
    get_principal,
    get_proposal_commands,
    get_proposal_queries,
)
from engram_api.schemas.common import PROBLEM_RESPONSES, ProvenanceView
from engram_api.schemas.proposals import (
    MergeResponse,
    OpenProposalRequest,
    ProposalDetailResponse,
    ProposalListResponse,
    ProposalResponse,
    ProposalTimelineEntryResponse,
    ProposalTimelineResponse,
    ReviewRequest,
    UndoResponse,
)
from engram_core.application.commands.proposal_commands import ProposalCommandService
from engram_core.application.dto import ProposalDetail
from engram_core.application.queries.proposal_queries import ProposalQueryService
from engram_core.domain.values import ProposalId
from engram_events import Provenance

router = APIRouter(prefix="/proposals", tags=["proposals"], responses=PROBLEM_RESPONSES)

Commands = Annotated[ProposalCommandService, Depends(get_proposal_commands)]
Queries = Annotated[ProposalQueryService, Depends(get_proposal_queries)]
Principal = Annotated[Provenance, Depends(get_principal)]


def _detail(detail: ProposalDetail) -> ProposalDetailResponse:
    """DTO → wire. A field rename, not a transformation."""
    return ProposalDetailResponse(
        id=UUID(str(detail.id)),
        title=detail.title,
        description=detail.description,
        status=detail.status,  # type: ignore[arg-type]
        review_note=detail.review_note,
        drafts=[dict(draft) for draft in detail.drafts],
        merged_event_ids=list(detail.merged_event_ids),
        version=detail.version,
    )


@router.get("", response_model=ProposalListResponse)
async def list_proposals(
    queries: Queries,
    status_filter: Annotated[str | None, Query(alias="status")] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> ProposalListResponse:
    """Open and recently closed proposals."""
    page = queries.list_proposals(status=status_filter, limit=limit)
    return ProposalListResponse(
        items=[
            ProposalResponse(
                id=UUID(str(item.id)),
                title=item.title,
                status=item.status,  # type: ignore[arg-type]
                review_note=item.review_note,
                draft_count=item.draft_count,
                opened_by=item.opened_by,
                created_at=item.created_at,
                updated_at=item.updated_at,
            )
            for item in page.items
        ],
        next_cursor=page.next_cursor,
    )


@router.get("/{proposal_id}", response_model=ProposalDetailResponse)
async def get_proposal(proposal_id: UUID, queries: Queries) -> ProposalDetailResponse:
    """One proposal in full, folded from its stream — draft intents included."""
    return _detail(queries.get_proposal(ProposalId(proposal_id)))


@router.get("/{proposal_id}/timeline", response_model=ProposalTimelineResponse)
async def proposal_timeline(proposal_id: UUID, queries: Queries) -> ProposalTimelineResponse:
    """The proposal's lifecycle as events, with the provenance the observatory reads."""
    entries = queries.timeline(ProposalId(proposal_id))
    return ProposalTimelineResponse(
        proposal_id=proposal_id,
        entries=[
            ProposalTimelineEntryResponse(
                event_id=entry.event_id,
                event_type=entry.event_type,
                occurred_at=entry.occurred_at,
                stream_seq=entry.stream_seq,
                provenance=ProvenanceView(
                    actor=entry.actor,
                    session_id=entry.session_id,
                    detail=entry.detail,
                ),
            )
            for entry in entries
        ],
    )


@router.post("", response_model=ProposalDetailResponse, status_code=status.HTTP_201_CREATED)
async def open_proposal(
    body: OpenProposalRequest,
    commands: Commands,
    queries: Queries,
    principal: Principal,
) -> ProposalDetailResponse:
    """Open a proposal carrying draft events for review."""
    proposal_id = commands.open_proposal(
        title=body.title,
        description=body.description,
        proposed_events=body.proposed_events,
        provenance=principal,
    )
    return _detail(queries.get_proposal(proposal_id))


@router.post("/{proposal_id}/approve", response_model=ProposalDetailResponse)
async def approve_proposal(
    proposal_id: UUID,
    body: ReviewRequest,
    commands: Commands,
    queries: Queries,
    principal: Principal,
) -> ProposalDetailResponse:
    """Approve an open proposal. Approval does not merge — two explicit steps."""
    identifier = ProposalId(proposal_id)
    commands.approve_proposal(identifier, body.note, principal)
    return _detail(queries.get_proposal(identifier))


@router.post("/{proposal_id}/reject", response_model=ProposalDetailResponse)
async def reject_proposal(
    proposal_id: UUID,
    body: ReviewRequest,
    commands: Commands,
    queries: Queries,
    principal: Principal,
) -> ProposalDetailResponse:
    """Reject an open proposal. Its drafts never become events."""
    identifier = ProposalId(proposal_id)
    commands.reject_proposal(identifier, body.note, principal)
    return _detail(queries.get_proposal(identifier))


@router.post("/{proposal_id}/merge", response_model=MergeResponse)
async def merge_proposal(
    proposal_id: UUID,
    commands: Commands,
    queries: Queries,
    principal: Principal,
) -> MergeResponse:
    """Execute an approved proposal. 409 when a target stream moved (conflict)."""
    identifier = ProposalId(proposal_id)
    appended = commands.merge_proposal(identifier, principal)
    return MergeResponse(
        proposal=_detail(queries.get_proposal(identifier)),
        appended_event_ids=list(appended),
    )


@router.post("/{proposal_id}/undo", response_model=UndoResponse)
async def undo_proposal(
    proposal_id: UUID,
    body: ReviewRequest,
    commands: Commands,
    queries: Queries,
    principal: Principal,
) -> UndoResponse:
    """Compensate a merged proposal (ADR-0018 §3). 409 unless it is merged."""
    identifier = ProposalId(proposal_id)
    compensating = commands.undo_proposal(identifier, body.note, principal)
    return UndoResponse(
        proposal=_detail(queries.get_proposal(identifier)),
        compensating_event_ids=list(compensating),
    )
