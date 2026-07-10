"""Value objects: identity, slugs, types, links, salience.

Identity rule (ADR-0003): a memory *is* its UUIDv7. Slugs and filenames are mutable,
human-friendly projections and must never be used as identity.
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


class MemoryType(StrEnum):
    """Coarse classification; also the top-level directory in the markdown export."""

    FACT = "fact"
    PREFERENCE = "preference"
    PROJECT = "project"
    REFERENCE = "reference"
    EPISODIC = "episodic"


class LinkRelation(StrEnum):
    """Typed graph edges between memories."""

    RELATES_TO = "relates_to"
    SUPERSEDES = "supersedes"
    DERIVED_FROM = "derived_from"
    CONTRADICTS = "contradicts"


@dataclass(frozen=True, slots=True)
class Link:
    """A directed, typed edge from the owning memory to ``target_id``."""

    target_id: MemoryId
    relation: LinkRelation


@dataclass(frozen=True, slots=True)
class Salience:
    """Inputs to future decay scoring. Fields only — the algorithm is roadmap work.

    Captured from day 1 (via ``MemoryAccessed`` events) so decay can be computed
    retroactively over the full history when it lands.
    """

    created_at: datetime
    last_accessed_at: datetime | None = None
    access_count: int = 0
