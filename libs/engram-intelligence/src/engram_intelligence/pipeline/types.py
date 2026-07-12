"""Stage-boundary data types. Frozen, transport-agnostic, and stable: any stage can
be swapped for a better model, a heuristic, or a human without its neighbors noticing.
"""

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from engram_core.domain.values import (
    EvidenceType,
    LinkRelation,
    MemoryId,
    MemoryKind,
    ProposalId,
)
from engram_events import Provenance


class TurnRole(StrEnum):
    USER = "user"
    ASSISTANT = "assistant"


@dataclass(frozen=True, slots=True)
class Turn:
    role: TurnRole
    content: str
    occurred_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class Transcript:
    """The pipeline's input: one conversation, with pipeline-wide provenance."""

    source: Provenance
    turns: tuple[Turn, ...]
    transcript_id: str | None = None


@dataclass(frozen=True, slots=True)
class Chunk:
    """A semantically coherent slice of the transcript (stage 1 output)."""

    index: int
    text: str
    turn_start: int
    turn_end: int


@dataclass(frozen=True, slots=True)
class ExtractedEvidence:
    """A verbatim quote worth remembering (stage 2 output). Travels through every
    later stage so merged proposals produce memories justified from birth."""

    chunk_index: int
    quote: str
    evidence_type: EvidenceType = EvidenceType.QUOTE
    rationale: str | None = None


@dataclass(frozen=True, slots=True)
class EntityMention:
    """A mention resolved (or not) against existing entity memories (stage 3)."""

    surface_text: str
    kind_guess: MemoryKind | None = None
    resolved_id: MemoryId | None = None
    resolution_confidence: float | None = None


@dataclass(frozen=True, slots=True)
class CandidateLink:
    """A proposed tier-1 edge. Targets either an existing memory or another
    candidate in the same batch (exactly one must be set)."""

    relation: LinkRelation
    target_memory_id: MemoryId | None = None
    target_candidate_index: int | None = None


@dataclass(frozen=True, slots=True)
class MemoryCandidate:
    """A draft typed memory (stage 4 output). ``attributes`` must already satisfy
    the kind schema — invalid candidates never leave the generator."""

    kind: MemoryKind
    title: str
    content: str
    attributes: dict[str, object]
    evidence: tuple[ExtractedEvidence, ...] = ()
    mentions: tuple[EntityMention, ...] = ()
    links: tuple[CandidateLink, ...] = ()
    confidence_prior: float | None = None
    duplicate_of: MemoryId | None = None


class ConflictClass(StrEnum):
    DUPLICATE = "duplicate"
    CONTRADICTION = "contradiction"


@dataclass(frozen=True, slots=True)
class ConflictReport:
    """A detected clash between a candidate and current state (stage 5 output)."""

    candidate_index: int
    conflict_class: ConflictClass
    existing_id: MemoryId
    detail: str


@dataclass(frozen=True, slots=True)
class ScoredCandidate:
    """A candidate with its importance prior attached (stage 6 output)."""

    candidate: MemoryCandidate
    importance: float
    rationale: str | None = None


@dataclass(frozen=True, slots=True)
class ProposalDraft:
    """What the assembler hands to the Proposal machinery (stage 7 output).

    ``prompt_versions`` records every prompt used (``name@version``) so the
    proposal is reproducible and attributable (ADR-0013).
    """

    title: str
    description: str
    proposed_events: tuple[dict[str, object], ...]
    prompt_versions: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class IngestionOutcome:
    """The pipeline's result: a proposal to review, or the reasons there is none."""

    proposal_id: ProposalId | None
    candidate_count: int
    conflict_count: int
    skipped_reasons: tuple[str, ...] = ()
