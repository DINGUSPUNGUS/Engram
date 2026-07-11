"""Value objects: identity, slugs, kinds, links, and the justification spine.

The model of record is docs/memory-model.md. Identity rule (ADR-0003): a memory *is*
its UUIDv7; slugs and filenames are mutable projections. Spine rule (ADR-0009): these
values record *signals*; scores are derived in projections.
"""

import re
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import NewType
from uuid import UUID

from engram_core.domain.errors import ValidationError
from engram_events import new_uuid7

MemoryId = NewType("MemoryId", UUID)
ProposalId = NewType("ProposalId", UUID)


def new_memory_id() -> MemoryId:
    """Mint a new immutable memory identity."""
    return MemoryId(new_uuid7())


def new_proposal_id() -> ProposalId:
    """Mint a new immutable proposal identity."""
    return ProposalId(new_uuid7())


_SLUG_PATTERN = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
_SLUG_MAX_LENGTH = 80


@dataclass(frozen=True, slots=True)
class Slug:
    """Human-friendly, URL- and filename-safe handle. Mutable over a memory's life.

    Lowercase alphanumerics separated by single hyphens; the constrained alphabet is
    also the path-traversal guard for the markdown exporter.
    """

    value: str

    def __post_init__(self) -> None:
        if len(self.value) > _SLUG_MAX_LENGTH:
            raise ValidationError(f"slug longer than {_SLUG_MAX_LENGTH} chars: {self.value!r}")
        if not _SLUG_PATTERN.fullmatch(self.value):
            raise ValidationError(f"invalid slug: {self.value!r}")

    def __str__(self) -> str:
        return self.value


class MemoryKind(StrEnum):
    """The twelve first-class memory kinds (memory-model.md §1-2, ADR-0008).

    Immutable after creation; also the top-level directory of the markdown export.
    """

    FACT = "fact"
    PREFERENCE = "preference"
    PERSON = "person"
    ORGANIZATION = "organization"
    PROJECT = "project"
    SKILL = "skill"
    GOAL = "goal"
    CONTACT = "contact"
    EVENT = "event"
    LOCATION = "location"
    ASSET = "asset"
    RELATIONSHIP = "relationship"


class LinkRelation(StrEnum):
    """Closed tier-1 edge vocabulary, canonical directions (memory-model.md §6).

    Extending this enum requires an ADR. Knowledge-bearing connections are reified
    as ``MemoryKind.RELATIONSHIP`` objects instead (ADR-0010).
    """

    ABOUT = "about"  # any memory -> the entity it concerns
    INVOLVES = "involves"  # project/event/goal -> person/org
    PART_OF = "part_of"  # member -> whole
    OWNED_BY = "owned_by"  # contact/asset -> person/org
    WORKS_AT = "works_at"  # person -> organization
    LOCATED_IN = "located_in"  # anything -> location
    RELATES_TO = "relates_to"  # symmetric, weakest
    SUPERSEDES = "supersedes"  # new -> old
    DERIVED_FROM = "derived_from"  # conclusion -> source
    CONTRADICTS = "contradicts"  # symmetric


@dataclass(frozen=True, slots=True)
class Link:
    """A directed, typed tier-1 edge from the owning memory to ``target_id``."""

    target_id: MemoryId
    relation: LinkRelation


# ---------------------------------------------------------------------------
# The justification spine (memory-model.md §3): why does this deserve to exist?
# ---------------------------------------------------------------------------


class EvidenceType(StrEnum):
    QUOTE = "quote"
    URI = "uri"
    CONVERSATION = "conversation"
    DOCUMENT = "document"
    OBSERVATION = "observation"


@dataclass(frozen=True, slots=True)
class EvidenceRef:
    """One piece of support for a memory. Append-only — corrections add evidence."""

    evidence_type: EvidenceType
    value: str
    note: str | None = None


class RetentionPolicy(StrEnum):
    PERMANENT = "permanent"  # never auto-archived
    STANDARD = "standard"  # subject to decay (default)
    UNTIL = "until"  # explicit expiry date
    EPHEMERAL = "ephemeral"  # auto-archive after the kind's short horizon


@dataclass(frozen=True, slots=True)
class Lifetime:
    """How long a memory should live (memory-model.md §4)."""

    policy: RetentionPolicy = RetentionPolicy.STANDARD
    until: datetime | None = None

    def __post_init__(self) -> None:
        if (self.policy is RetentionPolicy.UNTIL) != (self.until is not None):
            raise ValidationError("lifetime 'until' requires a date, other policies forbid one")


class Visibility(StrEnum):
    """Who may recall a memory. Enforced at the query/recall boundary."""

    SHARED = "shared"  # any connected assistant (default)
    PRIVATE = "private"  # dashboard/CLI only, never surfaced to assistants
    RESTRICTED = "restricted"  # allow-listed actors only


@dataclass(frozen=True, slots=True)
class ImportanceSignals:
    """Stored importance *signals*; scores are computed in projections (ADR-0009)."""

    created_at: datetime
    pinned: bool = False
    user_weight: float | None = None  # explicit 0..1 override, None = unset
    last_accessed_at: datetime | None = None
    access_count: int = 0

    def __post_init__(self) -> None:
        if self.user_weight is not None and not 0.0 <= self.user_weight <= 1.0:
            raise ValidationError(f"user_weight out of [0,1]: {self.user_weight}")


def validate_confidence(value: float) -> float:
    """Confidence is a plain float in [0,1]; every writer validates through here."""
    if not 0.0 <= value <= 1.0:
        raise ValidationError(f"confidence out of [0,1]: {value}")
    return value
