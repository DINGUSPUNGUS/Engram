"""The audit graph's node types.

A ``DecisionTrace`` answers one question about one subject ("why was this memory
created?", "why is confidence 0.73?", "why did evaluation person_001 fail?") as an
ordered chain of ``TraceStep``s. Traces are immutable once recorded — they are
evidence, and evidence is append-only everywhere in engram.
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from uuid import UUID

from engram_events import Provenance


class TraceSubject(StrEnum):
    """What a trace is about."""

    MEMORY = "memory"
    PROPOSAL = "proposal"
    EVALUATION = "evaluation"
    PIPELINE_RUN = "pipeline_run"


class StepCategory(StrEnum):
    """What kind of reasoning a step records."""

    RULE = "rule"  # a deterministic rule fired (schema check, conflict rule…)
    HEURISTIC = "heuristic"  # a non-LLM judgment (dedup threshold, noise filter…)
    PROMPT = "prompt"  # an LLM call: prompt@version + model_id + outcome
    EVIDENCE = "evidence"  # evidence considered or attached
    SCORE = "score"  # a number computed, with its inputs
    DECISION = "decision"  # the resulting choice (create / reject / flag / merge)


@dataclass(frozen=True, slots=True)
class TraceStep:
    """One link in the reasoning chain.

    ``data`` holds the step's structured inputs/outputs (JSON-compatible);
    ``prompt_ref`` is ``name@version`` (ADR-0013) and ``model_id`` is opaque
    provenance (ADR-0012) — recorded, never branched on.
    """

    seq: int
    category: StepCategory
    label: str
    detail: str = ""
    prompt_ref: str | None = None
    model_id: str | None = None
    evidence_refs: tuple[str, ...] = ()
    data: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class DecisionTrace:
    """One answered question about one subject."""

    trace_id: UUID
    subject: TraceSubject
    subject_id: UUID | None
    question: str
    outcome: str
    steps: tuple[TraceStep, ...]
    occurred_at: datetime
    provenance: Provenance
