"""Wire shapes for /memories — the twelve kinds plus the justification spine."""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field

MemoryKindName = Literal[
    "fact",
    "preference",
    "person",
    "organization",
    "project",
    "skill",
    "goal",
    "contact",
    "event",
    "location",
    "asset",
    "relationship",
]

LinkRelationName = Literal[
    "about",
    "involves",
    "part_of",
    "owned_by",
    "works_at",
    "located_in",
    "relates_to",
    "supersedes",
    "derived_from",
    "contradicts",
]

VisibilityName = Literal["shared", "private", "restricted"]
LifetimePolicyName = Literal["permanent", "standard", "until", "ephemeral"]
EvidenceTypeName = Literal["quote", "uri", "conversation", "document", "observation"]


class LinkView(BaseModel):
    target_id: UUID
    relation: LinkRelationName


class EvidenceView(BaseModel):
    evidence_type: EvidenceTypeName
    value: str
    note: str | None = None
    added_at: datetime | None = None
    actor: str | None = None


class MemoryResponse(BaseModel):
    id: UUID
    kind: MemoryKindName
    slug: str
    title: str
    content: str = Field(description="Narrative markdown; attributes are the queryable truth")
    attributes: dict[str, object] = Field(
        description="Kind-schema fields, validated on write (see docs/memory-model.md §2)"
    )
    tags: list[str]
    links: list[LinkView]
    evidence: list[EvidenceView]
    confidence: float = Field(ge=0, le=1)
    effective_confidence: float = Field(ge=0, le=1, description="Confidence after time decay")
    stale: bool = Field(description="Derived: effective confidence below the kind threshold")
    last_confirmed_at: datetime | None
    lifetime_policy: LifetimePolicyName
    lifetime_until: datetime | None
    visibility: VisibilityName
    pinned: bool
    user_weight: float | None = Field(default=None, ge=0, le=1)
    archived: bool
    created_at: datetime
    updated_at: datetime
    version: int = Field(description="Optimistic concurrency token; echo it in edits")


class MemoryListResponse(BaseModel):
    items: list[MemoryResponse]
    next_cursor: str | None = None


class CreateMemoryRequest(BaseModel):
    kind: MemoryKindName
    title: str = Field(min_length=1, max_length=500)
    content: str = ""
    attributes: dict[str, object] = Field(default={}, description="Must satisfy the kind schema")
    slug: str | None = Field(default=None, description="Derived from title when omitted")
    tags: list[str] = []
    confidence: float | None = Field(
        default=None, ge=0, le=1, description="Omit to apply the source prior"
    )
    lifetime_policy: LifetimePolicyName = "standard"
    lifetime_until: datetime | None = None
    visibility: VisibilityName = "shared"


class EditMemoryRequest(BaseModel):
    """Sparse narrative edit; omitted fields stay unchanged. ``kind`` is immutable —
    structured fields go through the attributes endpoint."""

    expected_version: int = Field(ge=1)
    title: str | None = None
    content: str | None = None
    slug: str | None = None


class UpdateAttributesRequest(BaseModel):
    expected_version: int = Field(ge=1)
    changes: dict[str, object] = Field(description="Sparse kind-schema field changes")


class ConfirmRequest(BaseModel):
    note: str | None = None


class ContradictRequest(BaseModel):
    contradicting_id: UUID | None = None
    note: str | None = None


class AddEvidenceRequest(BaseModel):
    evidence_type: EvidenceTypeName
    value: str = Field(min_length=1)
    note: str | None = None


class AdjustImportanceRequest(BaseModel):
    pinned: bool | None = None
    user_weight: float | None = Field(default=None, ge=0, le=1)


class SetVisibilityRequest(BaseModel):
    visibility: VisibilityName
    allowed_actors: list[str] = Field(
        default=[], description="Required (non-empty) iff visibility is 'restricted'"
    )


class SetLifetimeRequest(BaseModel):
    lifetime_policy: LifetimePolicyName
    lifetime_until: datetime | None = Field(
        default=None, description="Required iff policy is 'until'"
    )


class TimelineEntryResponse(BaseModel):
    event_id: UUID
    event_type: str
    occurred_at: datetime
    actor: str
    stream_seq: int


class TimelineResponse(BaseModel):
    memory_id: UUID
    entries: list[TimelineEntryResponse]
