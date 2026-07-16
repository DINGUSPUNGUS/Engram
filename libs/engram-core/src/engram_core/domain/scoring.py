"""The one tunable module for confidence, decay, retention, and importance
(ADR-0009, ADR-0019).

Constants plus the pure formulas that consume them. Two very different rules
apply (ADR-0019): weights for confirm/contradict resolve *at decide time* and are
recorded inside the event — so re-tuning them changes future decisions only —
while derived scores (effective confidence, retention, candidate importance) are
computed from stored signals and can be re-tuned for the whole corpus at any time.
Formulas of record: docs/memory-model.md §5 and §7.
"""

import math
from dataclasses import dataclass, field
from datetime import datetime

from engram_core.domain.values import MemoryKind

_SECONDS_PER_DAY = 86_400.0
_USER_ACTOR = "user"

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


#: Importance priors per kind for pipeline candidates (stage 6). Identity-level
#: kinds start high; episodic starts low. Boosts below add evidence/graph signal.
IMPORTANCE_KIND_BASE: dict[MemoryKind, float] = {
    MemoryKind.PERSON: 0.60,
    MemoryKind.ORGANIZATION: 0.55,
    MemoryKind.LOCATION: 0.45,
    MemoryKind.PREFERENCE: 0.55,
    MemoryKind.SKILL: 0.50,
    MemoryKind.FACT: 0.45,
    MemoryKind.GOAL: 0.55,
    MemoryKind.PROJECT: 0.55,
    MemoryKind.ASSET: 0.45,
    MemoryKind.RELATIONSHIP: 0.50,
    MemoryKind.CONTACT: 0.50,
    MemoryKind.EVENT: 0.30,
}

#: Per-item boosts for candidate importance (capped at 1.0 by the formula).
IMPORTANCE_EVIDENCE_BOOST = 0.10
IMPORTANCE_LINK_BOOST = 0.05
#: A candidate contradicting current state matters *more*, not less — it is the
#: one the human most needs to see.
IMPORTANCE_CONTRADICTION_BOOST = 0.15


@dataclass(frozen=True, slots=True)
class ScoringConfig:
    """Bundle handed to the scoring projection; a memory space may override it."""

    half_life_days: dict[MemoryKind, int] = field(default_factory=lambda: dict(HALF_LIFE_DAYS))
    staleness_threshold: dict[MemoryKind, float] = field(
        default_factory=lambda: dict(STALENESS_THRESHOLD)
    )
    retention_weights: RetentionWeights = DEFAULT_RETENTION_WEIGHTS
    pruning_threshold: float = PRUNING_CANDIDATE_THRESHOLD


# ---------------------------------------------------------------------------
# Decide-time resolution (recorded into events — ADR-0019 §1)
# ---------------------------------------------------------------------------


def confirm_weight_for(actor: str) -> float:
    """The confirmer's weight, resolved from provenance (user > assistant)."""
    return CONFIRM_WEIGHT_USER if actor == _USER_ACTOR else CONFIRM_WEIGHT_ASSISTANT


def contradict_weight_for(actor: str) -> float:
    """The disputer's weight, resolved from provenance (user > assistant)."""
    return CONTRADICT_WEIGHT_USER if actor == _USER_ACTOR else CONTRADICT_WEIGHT_ASSISTANT


# ---------------------------------------------------------------------------
# Fold-time formulas (consume weights recorded in events — memory-model.md §5)
# ---------------------------------------------------------------------------


def confirm_confidence(confidence: float, weight: float) -> float:
    """c' = c + (1-c)·w — confirmation moves confidence toward 1."""
    return min(confidence + (1.0 - confidence) * weight, 1.0)


def contradict_confidence(confidence: float, weight: float) -> float:
    """c' = c·(1-w) — contradiction decays confidence multiplicatively."""
    return max(confidence * (1.0 - weight), 0.0)


# ---------------------------------------------------------------------------
# Derived scores (never stored — ADR-0009)
# ---------------------------------------------------------------------------


def effective_confidence(
    confidence: float,
    kind: MemoryKind,
    anchor: datetime,
    now: datetime,
    config: ScoringConfig,
) -> float:
    """c_eff = c · 2^(-days_since_anchor / half_life_days) (memory-model.md §5).

    ``anchor`` is ``last_confirmed_at`` when set, else ``created_at``.
    """
    days = max((now - anchor).total_seconds() / _SECONDS_PER_DAY, 0.0)
    return confidence * math.pow(2.0, -days / config.half_life_days[kind])


def retention_score(
    *,
    kind: MemoryKind,
    effective_confidence: float,
    last_accessed_at: datetime | None,
    access_count: int,
    link_degree: int,
    user_weight: float | None,
    now: datetime,
    config: ScoringConfig,
) -> float:
    """retention = wr·recency + wf·log(1+accesses) + wc·centrality + wq·c_eff
    + wu·user_weight (memory-model.md §7). Pinned/permanent memories are exempt
    from pruning — exemption is the caller's rule; this is just the number.
    """
    weights = config.retention_weights
    anchor = last_accessed_at
    recency = 0.0
    if anchor is not None:
        days = max((now - anchor).total_seconds() / _SECONDS_PER_DAY, 0.0)
        recency = math.pow(2.0, -days / config.half_life_days[kind])
    frequency = math.log1p(access_count) / math.log1p(100)  # saturates around 100 accesses
    centrality = min(link_degree / 10.0, 1.0)
    return (
        weights.recency * recency
        + weights.frequency * min(frequency, 1.0)
        + weights.centrality * centrality
        + weights.confidence * effective_confidence
        + weights.user_weight * (user_weight or 0.0)
    )


def candidate_importance(
    kind: MemoryKind,
    *,
    evidence_count: int = 0,
    link_count: int = 0,
    contradicts_existing: bool = False,
) -> float:
    """Importance prior for a pipeline candidate (stage 6). Policy, not model:
    heuristics score first; models only when evaluations prove they beat these
    numbers (docs/intelligence.md §1)."""
    score = IMPORTANCE_KIND_BASE[kind]
    score += IMPORTANCE_EVIDENCE_BOOST * min(evidence_count, 3)
    score += IMPORTANCE_LINK_BOOST * min(link_count, 4)
    if contradicts_existing:
        score += IMPORTANCE_CONTRADICTION_BOOST
    return min(score, 1.0)
