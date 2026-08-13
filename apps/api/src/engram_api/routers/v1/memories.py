"""/memories — typed memory objects: CRUD (as events), the justification spine,
timeline, undo.

Every handler parses input, calls one service, and maps the result (ADR-0007).
Model of record: docs/memory-model.md.
"""

from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, status

from engram_api.dependencies import (
    get_history_queries,
    get_memory_commands,
    get_memory_queries,
    get_principal,
    get_timeline_queries,
)
from engram_api.schemas.common import PROBLEM_RESPONSES, ProvenanceView
from engram_api.schemas.memories import (
    AddEvidenceRequest,
    AdjustImportanceRequest,
    ConfirmRequest,
    ContradictRequest,
    CreateMemoryRequest,
    EditMemoryRequest,
    EvidenceView,
    LinkView,
    MemoryKindName,
    MemoryListResponse,
    MemoryResponse,
    MemorySnapshotResponse,
    SetLifetimeRequest,
    SetVisibilityRequest,
    TimelineEntryResponse,
    TimelineResponse,
    UndoResponse,
    UpdateAttributesRequest,
)
from engram_core.application.commands.memory_commands import MemoryCommandService
from engram_core.application.dto import (
    CreateMemoryInput,
    EditMemoryInput,
    MemoryReadModel,
    MemorySnapshot,
    UpdateAttributesInput,
)
from engram_core.application.queries.history_queries import HistoryQueryService
from engram_core.application.queries.memory_queries import MemoryQueryService
from engram_core.application.queries.timeline_queries import TimelineQueryService
from engram_core.domain.errors import ValidationError
from engram_core.domain.values import (
    EvidenceRef,
    EvidenceType,
    Lifetime,
    MemoryId,
    MemoryKind,
    RetentionPolicy,
    Visibility,
)
from engram_events import Provenance

router = APIRouter(prefix="/memories", tags=["memories"], responses=PROBLEM_RESPONSES)

Commands = Annotated[MemoryCommandService, Depends(get_memory_commands)]
Queries = Annotated[MemoryQueryService, Depends(get_memory_queries)]
Timeline = Annotated[TimelineQueryService, Depends(get_timeline_queries)]
History = Annotated[HistoryQueryService, Depends(get_history_queries)]
Principal = Annotated[Provenance, Depends(get_principal)]


# -- DTO <-> wire mapping (a field rename, not a transformation; ADR-0021 §1) ----


def _response(model: MemoryReadModel) -> MemoryResponse:
    return MemoryResponse(
        id=UUID(str(model.id)),
        kind=model.kind.value,
        slug=model.slug,
        title=model.title,
        content=model.content,
        attributes=model.attributes,
        tags=list(model.tags),
        links=[
            LinkView(
                target_id=UUID(str(link.target_id)),
                relation=link.relation,  # type: ignore[arg-type]
            )
            for link in model.links
        ],
        evidence=[
            EvidenceView(
                evidence_type=item.evidence_type,  # type: ignore[arg-type]
                value=item.value,
                note=item.note,
                added_at=item.added_at,
                actor=item.actor,
            )
            for item in model.evidence
        ],
        confidence=model.confidence,
        effective_confidence=model.effective_confidence,
        stale=model.stale,
        last_confirmed_at=model.last_confirmed_at,
        lifetime_policy=model.lifetime_policy,  # type: ignore[arg-type]
        lifetime_until=model.lifetime_until,
        visibility=model.visibility,  # type: ignore[arg-type]
        pinned=model.pinned,
        user_weight=model.user_weight,
        archived=model.archived,
        created_at=model.created_at,
        updated_at=model.updated_at,
        version=model.version,
    )


def _snapshot_response(snapshot: MemorySnapshot) -> MemorySnapshotResponse:
    return MemorySnapshotResponse(
        id=UUID(str(snapshot.id)),
        kind=snapshot.kind.value,
        slug=snapshot.slug,
        title=snapshot.title,
        content=snapshot.content,
        attributes=snapshot.attributes,
        tags=list(snapshot.tags),
        confidence=snapshot.confidence,
        lifetime_policy=snapshot.lifetime_policy,  # type: ignore[arg-type]
        visibility=snapshot.visibility,  # type: ignore[arg-type]
        archived=snapshot.archived,
        deleted=snapshot.deleted,
        version=snapshot.version,
    )


def _lifetime(policy: str, until: datetime | None) -> Lifetime:
    return Lifetime(RetentionPolicy(policy), until)


# -- listing & core content -----------------------------------------------------


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
    """Cursor-paginated listing. Visibility enforcement against the principal
    arrives with the auth milestone; today every caller is the owning user."""
    page = queries.list_memories(
        kind=MemoryKind(kind) if kind is not None else None,
        tag=tag,
        include_archived=include_archived,
        include_stale=include_stale,
        cursor=cursor,
        limit=limit,
    )
    return MemoryListResponse(
        items=[_response(m) for m in page.items], next_cursor=page.next_cursor
    )


@router.post("", response_model=MemoryResponse, status_code=status.HTTP_201_CREATED)
async def create_memory(
    body: CreateMemoryRequest, commands: Commands, queries: Queries, principal: Principal
) -> MemoryResponse:
    """Create a typed memory; attributes must satisfy the kind schema (422 otherwise)."""
    memory_id = commands.create_memory(
        CreateMemoryInput(
            kind=MemoryKind(body.kind),
            title=body.title,
            content=body.content,
            attributes=body.attributes,
            slug=body.slug,
            tags=tuple(body.tags),
            confidence=body.confidence,
            lifetime=_lifetime(body.lifetime_policy, body.lifetime_until),
            visibility=Visibility(body.visibility),
        ),
        principal,
    )
    return _response(queries.get_memory(memory_id))


@router.get("/{memory_id}", response_model=MemoryResponse)
async def get_memory(memory_id: UUID, queries: Queries, principal: Principal) -> MemoryResponse:
    """Current state of one memory, spine included."""
    return _response(queries.get_memory(MemoryId(memory_id)))


@router.patch("/{memory_id}", response_model=MemoryResponse)
async def edit_memory(
    memory_id: UUID,
    body: EditMemoryRequest,
    commands: Commands,
    queries: Queries,
    principal: Principal,
) -> MemoryResponse:
    """Sparse narrative edit (title/content/slug). 409 when ``expected_version`` is stale."""
    identifier = MemoryId(memory_id)
    commands.edit_memory(
        identifier,
        EditMemoryInput(
            expected_version=body.expected_version,
            title=body.title,
            content=body.content,
            slug=body.slug,
        ),
        principal,
    )
    return _response(queries.get_memory(identifier))


@router.patch("/{memory_id}/attributes", response_model=MemoryResponse)
async def update_attributes(
    memory_id: UUID,
    body: UpdateAttributesRequest,
    commands: Commands,
    queries: Queries,
    principal: Principal,
) -> MemoryResponse:
    """Sparse change to kind-schema fields; validated against the KindRegistry."""
    identifier = MemoryId(memory_id)
    commands.update_attributes(
        identifier,
        UpdateAttributesInput(expected_version=body.expected_version, changes=body.changes),
        principal,
    )
    return _response(queries.get_memory(identifier))


@router.delete("/{memory_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_memory(
    memory_id: UUID,
    commands: Commands,
    principal: Principal,
    reason: Annotated[str | None, Query()] = None,
) -> None:
    """Tombstone the memory (its history remains in the event log). Never called
    by automation (ADR-0011) — there is no proposal-driven path to this route."""
    commands.delete_memory(MemoryId(memory_id), reason, principal)


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
    identifier = MemoryId(memory_id)
    commands.confirm_memory(identifier, body.note, principal)
    return _response(queries.get_memory(identifier))


@router.post("/{memory_id}/contradict", response_model=MemoryResponse)
async def contradict_memory(
    memory_id: UUID,
    body: ContradictRequest,
    commands: Commands,
    queries: Queries,
    principal: Principal,
) -> MemoryResponse:
    """Dispute a memory: lowers confidence, creates a ``contradicts`` edge."""
    identifier = MemoryId(memory_id)
    contradicting = MemoryId(body.contradicting_id) if body.contradicting_id is not None else None
    commands.contradict_memory(identifier, contradicting, body.note, principal)
    return _response(queries.get_memory(identifier))


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
    identifier = MemoryId(memory_id)
    commands.add_evidence(
        identifier,
        EvidenceRef(EvidenceType(body.evidence_type), body.value, body.note),
        principal,
    )
    return _response(queries.get_memory(identifier))


@router.patch("/{memory_id}/importance", response_model=MemoryResponse)
async def adjust_importance(
    memory_id: UUID,
    body: AdjustImportanceRequest,
    commands: Commands,
    queries: Queries,
    principal: Principal,
) -> MemoryResponse:
    """Pin/unpin or set the explicit user weight."""
    identifier = MemoryId(memory_id)
    commands.adjust_importance(
        identifier, pinned=body.pinned, user_weight=body.user_weight, provenance=principal
    )
    return _response(queries.get_memory(identifier))


@router.patch("/{memory_id}/visibility", response_model=MemoryResponse)
async def set_visibility(
    memory_id: UUID,
    body: SetVisibilityRequest,
    commands: Commands,
    queries: Queries,
    principal: Principal,
) -> MemoryResponse:
    """Change who may recall this memory."""
    identifier = MemoryId(memory_id)
    commands.set_visibility(
        identifier, Visibility(body.visibility), tuple(body.allowed_actors), principal
    )
    return _response(queries.get_memory(identifier))


@router.patch("/{memory_id}/lifetime", response_model=MemoryResponse)
async def set_lifetime(
    memory_id: UUID,
    body: SetLifetimeRequest,
    commands: Commands,
    queries: Queries,
    principal: Principal,
) -> MemoryResponse:
    """Change the retention policy."""
    identifier = MemoryId(memory_id)
    commands.set_lifetime(
        identifier, _lifetime(body.lifetime_policy, body.lifetime_until), principal
    )
    return _response(queries.get_memory(identifier))


# -- history --------------------------------------------------------------------


@router.get("/{memory_id}/timeline", response_model=TimelineResponse)
async def memory_timeline(memory_id: UUID, timeline: Timeline) -> TimelineResponse:
    """Full event history of one memory, oldest first — provenance included,
    the same shape the Observatory reads (ADR-0021 §3, ADR-0022)."""
    entries = timeline.memory_timeline(MemoryId(memory_id))
    return TimelineResponse(
        memory_id=memory_id,
        entries=[
            TimelineEntryResponse(
                event_id=entry.event_id,
                event_type=entry.event_type,
                occurred_at=entry.occurred_at,
                stream_seq=entry.stream_seq,
                provenance=ProvenanceView(
                    actor=entry.actor, session_id=entry.session_id, detail=entry.detail
                ),
            )
            for entry in entries
        ],
    )


@router.get("/{memory_id}/at", response_model=MemorySnapshotResponse)
async def memory_at(
    memory_id: UUID,
    history: History,
    at: Annotated[datetime | None, Query(description="Instant to reconstruct (ISO-8601)")] = None,
    version: Annotated[int | None, Query(ge=1, description="Stream version to reconstruct")] = None,
) -> MemorySnapshotResponse:
    """Time travel (ADR-0002/ADR-0021): the memory exactly as it was at a moment
    or version. Exactly one of ``at``/``version`` is required (422 otherwise)."""
    if (at is None) == (version is None):
        raise ValidationError("time travel needs exactly one of ?at= or ?version=")
    snapshot = history.state_at(MemoryId(memory_id), at=at, version=version)
    return _snapshot_response(snapshot)


@router.post("/{memory_id}/undo", response_model=UndoResponse)
async def undo_last_change(
    memory_id: UUID, commands: Commands, queries: Queries, principal: Principal
) -> UndoResponse:
    """Append the compensating event for the most recent change on this memory
    (ADR-0021). 409 when the last event has no defined inverse."""
    identifier = MemoryId(memory_id)
    compensating_id = commands.undo_last_change(identifier, principal)
    return UndoResponse(
        memory=_response(queries.get_memory(identifier)), compensating_event_id=compensating_id
    )
