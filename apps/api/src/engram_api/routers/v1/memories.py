"""/memories — typed memory objects: CRUD (as events), the justification spine,
timeline, undo.

Every handler is a stub: the route, schema, and status contract are final;
``NotImplementedError`` maps to a 501 problem response. Model of record:
docs/memory-model.md.
"""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, status

from engram_api.dependencies import (
    get_memory_commands,
    get_memory_queries,
    get_principal,
    get_timeline_queries,
)
from engram_api.schemas.common import PROBLEM_RESPONSES
from engram_api.schemas.memories import (
    AddEvidenceRequest,
    AdjustImportanceRequest,
    ConfirmRequest,
    ContradictRequest,
    CreateMemoryRequest,
    EditMemoryRequest,
    MemoryKindName,
    MemoryListResponse,
    MemoryResponse,
    SetLifetimeRequest,
    SetVisibilityRequest,
    TimelineResponse,
    UpdateAttributesRequest,
)
from engram_core.application.commands.memory_commands import MemoryCommandService
from engram_core.application.queries.memory_queries import MemoryQueryService
from engram_core.application.queries.timeline_queries import TimelineQueryService
from engram_events import Provenance

router = APIRouter(prefix="/memories", tags=["memories"], responses=PROBLEM_RESPONSES)

Commands = Annotated[MemoryCommandService, Depends(get_memory_commands)]
Queries = Annotated[MemoryQueryService, Depends(get_memory_queries)]
Timeline = Annotated[TimelineQueryService, Depends(get_timeline_queries)]
Principal = Annotated[Provenance, Depends(get_principal)]


@router.get("", response_model=MemoryListResponse)
async def list_memories(
    queries: Queries,
    principal: Principal,
    kind: Annotated[MemoryKindName | None, Query()] = None,
    tag: Annotated[str | None, Query()] = None,
    include_archived: Annotated[bool, Query()] = False,
    include_stale: Annotated[bool, Query()] = True,
    cursor: Annotated[str | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> MemoryListResponse:
    """Cursor-paginated listing. Visibility is enforced against the principal."""
    raise NotImplementedError


@router.post("", response_model=MemoryResponse, status_code=status.HTTP_201_CREATED)
async def create_memory(
    body: CreateMemoryRequest, commands: Commands, queries: Queries, principal: Principal
) -> MemoryResponse:
    """Create a typed memory; attributes must satisfy the kind schema (422 otherwise)."""
    raise NotImplementedError


@router.get("/{memory_id}", response_model=MemoryResponse)
async def get_memory(memory_id: UUID, queries: Queries, principal: Principal) -> MemoryResponse:
    """Current state of one memory, spine included."""
    raise NotImplementedError


@router.patch("/{memory_id}", response_model=MemoryResponse)
async def edit_memory(
    memory_id: UUID,
    body: EditMemoryRequest,
    commands: Commands,
    queries: Queries,
    principal: Principal,
) -> MemoryResponse:
    """Sparse narrative edit (title/content/slug). 409 when ``expected_version`` is stale."""
    raise NotImplementedError


@router.patch("/{memory_id}/attributes", response_model=MemoryResponse)
async def update_attributes(
    memory_id: UUID,
    body: UpdateAttributesRequest,
    commands: Commands,
    queries: Queries,
    principal: Principal,
) -> MemoryResponse:
    """Sparse change to kind-schema fields; validated against the KindRegistry."""
    raise NotImplementedError


@router.delete("/{memory_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_memory(memory_id: UUID, commands: Commands, principal: Principal) -> None:
    """Tombstone the memory (its history remains in the event log)."""
    raise NotImplementedError


# -- justification spine ------------------------------------------------------


@router.post("/{memory_id}/confirm", response_model=MemoryResponse)
async def confirm_memory(
    memory_id: UUID,
    body: ConfirmRequest,
    commands: Commands,
    queries: Queries,
    principal: Principal,
) -> MemoryResponse:
    """Vouch for a memory: raises confidence, resets staleness."""
    raise NotImplementedError


@router.post("/{memory_id}/contradict", response_model=MemoryResponse)
async def contradict_memory(
    memory_id: UUID,
    body: ContradictRequest,
    commands: Commands,
    queries: Queries,
    principal: Principal,
) -> MemoryResponse:
    """Dispute a memory: lowers confidence, creates a ``contradicts`` edge."""
    raise NotImplementedError


@router.post(
    "/{memory_id}/evidence", response_model=MemoryResponse, status_code=status.HTTP_201_CREATED
)
async def add_evidence(
    memory_id: UUID,
    body: AddEvidenceRequest,
    commands: Commands,
    queries: Queries,
    principal: Principal,
) -> MemoryResponse:
    """Append supporting evidence (append-only)."""
    raise NotImplementedError


@router.patch("/{memory_id}/importance", response_model=MemoryResponse)
async def adjust_importance(
    memory_id: UUID,
    body: AdjustImportanceRequest,
    commands: Commands,
    queries: Queries,
    principal: Principal,
) -> MemoryResponse:
    """Pin/unpin or set the explicit user weight."""
    raise NotImplementedError


@router.patch("/{memory_id}/visibility", response_model=MemoryResponse)
async def set_visibility(
    memory_id: UUID,
    body: SetVisibilityRequest,
    commands: Commands,
    queries: Queries,
    principal: Principal,
) -> MemoryResponse:
    """Change who may recall this memory."""
    raise NotImplementedError


@router.patch("/{memory_id}/lifetime", response_model=MemoryResponse)
async def set_lifetime(
    memory_id: UUID,
    body: SetLifetimeRequest,
    commands: Commands,
    queries: Queries,
    principal: Principal,
) -> MemoryResponse:
    """Change the retention policy."""
    raise NotImplementedError


# -- history ------------------------------------------------------------------


@router.get("/{memory_id}/timeline", response_model=TimelineResponse)
async def memory_timeline(memory_id: UUID, timeline: Timeline) -> TimelineResponse:
    """Full event history of one memory, oldest first."""
    raise NotImplementedError


@router.post("/{memory_id}/undo", response_model=MemoryResponse)
async def undo_last_change(
    memory_id: UUID, commands: Commands, queries: Queries, principal: Principal
) -> MemoryResponse:
    """Append the compensating event for the most recent change."""
    raise NotImplementedError
