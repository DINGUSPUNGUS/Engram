"""/memories — CRUD (as events), timeline, undo.

Every handler is an architecture-phase stub: the route, schema, and status
contract are final; ``NotImplementedError`` maps to a 501 problem response.
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
    CreateMemoryRequest,
    EditMemoryRequest,
    MemoryListResponse,
    MemoryResponse,
    MemoryTypeName,
    TimelineResponse,
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
    memory_type: Annotated[MemoryTypeName | None, Query()] = None,
    tag: Annotated[str | None, Query()] = None,
    include_archived: Annotated[bool, Query()] = False,
    cursor: Annotated[str | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> MemoryListResponse:
    """Cursor-paginated listing of current memory state."""
    raise NotImplementedError


@router.post("", response_model=MemoryResponse, status_code=status.HTTP_201_CREATED)
async def create_memory(
    body: CreateMemoryRequest, commands: Commands, queries: Queries, principal: Principal
) -> MemoryResponse:
    """Create a memory; returns its immutable id and initial state."""
    raise NotImplementedError


@router.get("/{memory_id}", response_model=MemoryResponse)
async def get_memory(memory_id: UUID, queries: Queries) -> MemoryResponse:
    """Current state of one memory."""
    raise NotImplementedError


@router.patch("/{memory_id}", response_model=MemoryResponse)
async def edit_memory(
    memory_id: UUID,
    body: EditMemoryRequest,
    commands: Commands,
    queries: Queries,
    principal: Principal,
) -> MemoryResponse:
    """Sparse edit. 409 when ``expected_version`` is stale."""
    raise NotImplementedError


@router.delete("/{memory_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_memory(memory_id: UUID, commands: Commands, principal: Principal) -> None:
    """Tombstone the memory (its history remains in the event log)."""
    raise NotImplementedError


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
