"""The one tunable module for confidence, decay, and retention (ADR-0009).

Constants only — the formulas that consume them live in the (future) scoring
projection. Because scores are derived and never stored in the event log, every
number here can be re-tuned and the whole corpus rescored via ``engram rebuild``.
Formulas of record: docs/memory-model.md §5 and §7.
"""

from dataclasses import dataclass, field

from engram_core.domain.values import MemoryKind

#: Confidence priors by creation source (memory-model.md §5).
CONFIDENCE_PRIOR_USER_STATED = 0.95
CONFIDENCE_PRIOR_ASSISTANT_INFERRED = 0.60
CONFIDENCE_PRIOR_IMPORTED = 0.70

#: Confirmation weights: c' = c + (1-c)*w
CONFIRM_WEIGHT_USER = 0.90
CONFIRM_WEIGHT_ASSISTANT = 0.40
CONFIRM_WEIGHT_EVIDENCE = 0.20

#: Contradiction decay: c' = c * (1-w)
CONTRADICT_WEIGHT_USER = 0.80
CONTRADICT_WEIGHT_ASSISTANT = 0.40

#: Effective-confidence half-life and staleness threshold per kind
#: (memory-model.md §7). c_eff = c * 2^(-days_since_confirmed / half_life_days).
HALF_LIFE_DAYS: dict[MemoryKind, int] = {
    MemoryKind.PERSON: 730,
    MemoryKind.ORGANIZATION: 730,
    MemoryKind.LOCATION: 730,
    MemoryKind.PREFERENCE: 365,
    MemoryKind.SKILL: 365,
    MemoryKind.FACT: 365,
    MemoryKind.GOAL: 180,
    MemoryKind.PROJECT: 180,  # ACTIVE projects are exempt from pruning
    MemoryKind.ASSET: 180,
    MemoryKind.RELATIONSHIP: 180,
    MemoryKind.CONTACT: 180,
    MemoryKind.EVENT: 30,
}

STALENESS_THRESHOLD: dict[MemoryKind, float] = {
    MemoryKind.PERSON: 0.30,
    MemoryKind.ORGANIZATION: 0.30,
    MemoryKind.LOCATION: 0.30,
    MemoryKind.PREFERENCE: 0.35,
    MemoryKind.SKILL: 0.35,
    MemoryKind.FACT: 0.35,
    MemoryKind.GOAL: 0.40,
    MemoryKind.PROJECT: 0.40,
    MemoryKind.ASSET: 0.40,
    MemoryKind.RELATIONSHIP: 0.40,
    MemoryKind.CONTACT: 0.40,
    MemoryKind.EVENT: 0.50,
}


@dataclass(frozen=True, slots=True)
class RetentionWeights:
    """retention_score = wr*recency + wf*log(1+access_count) + wc*centrality
    + wq*c_eff + wu*user_weight; pinned/permanent memories are exempt."""

    recency: float = 0.35
    frequency: float = 0.20
    centrality: float = 0.15
    confidence: float = 0.20
    user_weight: float = 0.10


DEFAULT_RETENTION_WEIGHTS = RetentionWeights()

#: Below this retention score, a memory becomes a candidate for the archive
#: Proposal (ADR-0011 — pruning proposes, it never deletes).
PRUNING_CANDIDATE_THRESHOLD = 0.15


@dataclass(frozen=True, slots=True)
class ScoringConfig:
    """Bundle handed to the scoring projection; a memory space may override it."""

    half_life_days: dict[MemoryKind, int] = field(default_factory=lambda: dict(HALF_LIFE_DAYS))
    staleness_threshold: dict[MemoryKind, float] = field(
        default_factory=lambda: dict(STALENESS_THRESHOLD)
    )
    retention_weights: RetentionWeights = DEFAULT_RETENTION_WEIGHTS
    pruning_threshold: float = PRUNING_CANDIDATE_THRESHOLD
