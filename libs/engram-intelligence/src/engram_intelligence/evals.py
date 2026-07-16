"""Evaluation harness contracts (ADR-0014).

Golden cases live in evaluations/golden/ (markdown: frontmatter + conversation +
expected-outcome YAML); the committed baseline lives in
evaluations/results/baseline.json. The gate: no AI-affecting change merges below
baseline; improvements update the baseline in the same PR.
"""

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

import yaml

from engram_core.domain.errors import ValidationError
from engram_events import Provenance
from engram_intelligence.pipeline.types import Transcript, Turn, TurnRole


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


_TURN_PATTERN = re.compile(r"^(USER|ASSISTANT):\s?(.*)$")


def load_golden_cases(directory: Path) -> Sequence[EvalCase]:
    """Parse evaluations/golden/*.md into cases (format: docs/intelligence.md §4).

    Raises:
        ValidationError: malformed frontmatter, missing sections, or bad YAML.
    """
    return tuple(_parse_case(path) for path in sorted(directory.glob("*.md")))


def _parse_case(path: Path) -> EvalCase:
    text = path.read_text(encoding="utf-8-sig")
    if not text.startswith("---"):
        raise ValidationError(f"golden case has no frontmatter: {path.name}")
    try:
        _, frontmatter, body = text.split("---", 2)
        meta = yaml.safe_load(frontmatter)
    except (ValueError, yaml.YAMLError) as exc:
        raise ValidationError(f"golden case frontmatter is broken ({path.name}): {exc}") from exc
    if not isinstance(meta, dict) or "id" not in meta:
        raise ValidationError(f"golden case frontmatter needs at least an id: {path.name}")

    conversation = _section(body, "Conversation", path.name)
    expected_raw = _section(body, "Expected", path.name)
    fence = re.search(r"```yaml\n(.*?)```", expected_raw, re.DOTALL)
    try:
        expected = yaml.safe_load(fence.group(1)) if fence else {}
    except yaml.YAMLError as exc:
        raise ValidationError(f"golden case expected-YAML is broken ({path.name}): {exc}") from exc

    case_id = str(meta["id"])
    return EvalCase(
        case_id=case_id,
        scenario=str(meta.get("scenario", "")),
        stages=tuple(str(stage) for stage in meta.get("stages", ())),
        transcript=Transcript(
            source=Provenance(actor="golden", session_id=case_id),
            turns=_parse_turns(conversation, path.name),
            transcript_id=case_id,
        ),
        expected=dict(expected) if isinstance(expected, dict) else {},
        source_path=path,
    )


def _section(body: str, heading: str, name: str) -> str:
    match = re.search(rf"^## {heading}\n(.*?)(?=^## |\Z)", body, re.DOTALL | re.MULTILINE)
    if match is None:
        raise ValidationError(f"golden case lacks a '## {heading}' section: {name}")
    return match.group(1)


def _parse_turns(conversation: str, name: str) -> tuple[Turn, ...]:
    """USER:/ASSISTANT:-prefixed turns; unprefixed lines continue the turn."""
    turns: list[tuple[TurnRole, list[str]]] = []
    for line in conversation.splitlines():
        match = _TURN_PATTERN.match(line)
        if match:
            turns.append((TurnRole(match.group(1).lower()), [match.group(2)]))
        elif line.strip() and turns:
            turns[-1][1].append(line.strip())
    if not turns:
        raise ValidationError(f"golden case conversation has no turns: {name}")
    return tuple(Turn(role=role, content=" ".join(lines).strip()) for role, lines in turns)


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
