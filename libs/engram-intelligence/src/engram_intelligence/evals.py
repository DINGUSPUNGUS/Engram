"""Evaluation harness contracts (ADR-0014).

Golden cases live in evaluations/golden/ (markdown: frontmatter + conversation +
expected-outcome YAML); the committed baseline lives in
evaluations/results/baseline.json. The gate: no AI-affecting change merges below
baseline; improvements update the baseline in the same PR.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from engram_intelligence.pipeline.types import Transcript


@dataclass(frozen=True, slots=True)
class EvalCase:
    """One golden case: a conversation and the outcome the pipeline must produce."""

    case_id: str
    scenario: str
    stages: tuple[str, ...]
    transcript: Transcript
    expected: dict[str, object]
    source_path: Path | None = None


@dataclass(frozen=True, slots=True)
class EvalScore:
    """One stage's score on one case. ``score`` is 0..1, comparable only within a
    (provider, model) configuration for LLM-backed stages."""

    case_id: str
    stage: str
    score: float
    passed: bool
    detail: str = ""


class StageEvaluator(Protocol):
    """Scores one pipeline stage against a case's expectations."""

    @property
    def stage(self) -> str: ...

    def evaluate(self, case: EvalCase) -> EvalScore: ...


def load_golden_cases(directory: Path) -> Sequence[EvalCase]:
    """Parse evaluations/golden/*.md into cases (format: docs/intelligence.md §4).
    Implementation lands with the pipeline (roadmap phase 8)."""
    raise NotImplementedError


def check_regression(
    baseline: Mapping[str, float],
    current: Mapping[str, float],
    *,
    tolerance: float = 0.0,
) -> tuple[str, ...]:
    """The gate itself: compare per-stage mean scores against the committed baseline.

    Returns the names of regressed stages (empty tuple = gate passes). A stage
    present in the baseline but missing from ``current`` is a regression — silently
    dropping an evaluation is how quality erodes.
    """
    regressed = [
        stage
        for stage, baseline_score in baseline.items()
        if current.get(stage, float("-inf")) < baseline_score - tolerance
    ]
    return tuple(sorted(regressed))
