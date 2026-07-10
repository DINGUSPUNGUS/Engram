"""/proposals — PR-style review of memory changes. Architecture-phase stubs."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, status

from engram_api.dependencies import get_principal, get_proposal_commands
from engram_api.schemas.common import PROBLEM_RESPONSES
from engram_api.schemas.proposals import (
    OpenProposalRequest,
    ProposalListResponse,
    ProposalResponse,
    ReviewRequest,
)
from engram_core.application.commands.proposal_commands import ProposalCommandService
from engram_events import Provenance

router = APIRouter(prefix="/proposals", tags=["proposals"], responses=PROBLEM_RESPONSES)

Commands = Annotated[ProposalCommandService, Depends(get_proposal_commands)]
Principal = Annotated[Provenance, Depends(get_principal)]


@router.get("", response_model=ProposalListResponse)
async def list_proposals(commands: Commands) -> ProposalListResponse:
    """Open and recently closed proposals."""
    raise NotImplementedError


@router.post("", response_model=ProposalResponse, status_code=status.HTTP_201_CREATED)
async def open_proposal(
    body: OpenProposalRequest, commands: Commands, principal: Principal
) -> ProposalResponse:
    """Open a proposal carrying draft events for review."""
    raise NotImplementedError


@router.post("/{proposal_id}/approve", response_model=ProposalResponse)
async def approve_proposal(
    proposal_id: UUID, body: ReviewRequest, commands: Commands, principal: Principal
) -> ProposalResponse:
    raise NotImplementedError


@router.post("/{proposal_id}/reject", response_model=ProposalResponse)
async def reject_proposal(
    proposal_id: UUID, body: ReviewRequest, commands: Commands, principal: Principal
) -> ProposalResponse:
    raise NotImplementedError


@router.post("/{proposal_id}/merge", response_model=ProposalResponse)
async def merge_proposal(
    proposal_id: UUID, commands: Commands, principal: Principal
) -> ProposalResponse:
    """Execute an approved proposal. 409 when a target stream moved (conflict)."""
    raise NotImplementedError
