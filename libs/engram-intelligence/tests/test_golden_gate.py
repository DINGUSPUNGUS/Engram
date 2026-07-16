"""The evaluation gate (ADR-0014), running for real: golden cases load, the
deterministic stages run in CI on every change, and the committed baseline is
the number that must not go down."""

import json
from pathlib import Path

import pytest
from engram_intelligence.evals import check_regression, load_golden_cases
from engram_intelligence.evaluators import deterministic_evaluators, run_suite
from engram_intelligence.pipeline.types import TurnRole

from engram_core.domain.kinds import build_kind_registry

_REPO_ROOT = Path(__file__).resolve().parents[3]
GOLDEN_DIR = _REPO_ROOT / "evaluations" / "golden"
BASELINE_PATH = _REPO_ROOT / "evaluations" / "results" / "baseline.json"
KINDS = build_kind_registry()


@pytest.mark.unit
def test_golden_cases_load_with_transcripts_and_expectations() -> None:
    cases = load_golden_cases(GOLDEN_DIR)
    assert {case.case_id for case in cases} == {"person_001", "preference_002", "project_017"}
    person = next(case for case in cases if case.case_id == "person_001")
    assert person.transcript.turns[0].role is TurnRole.USER
    assert "Sarah Chen" in person.transcript.turns[0].content
    assert person.expected["candidates"]
    preference = next(case for case in cases if case.case_id == "preference_002")
    assert preference.expected["existing"]  # fixture state travels with the case


@pytest.mark.unit
def test_deterministic_stages_meet_the_committed_baseline() -> None:
    cases = load_golden_cases(GOLDEN_DIR)
    current, scores = run_suite(cases, deterministic_evaluators(KINDS))
    failures = [s for s in scores if not s.passed]
    assert not failures, "; ".join(f"{s.stage}/{s.case_id}: {s.detail}" for s in failures)

    baseline_doc = json.loads(BASELINE_PATH.read_text(encoding="utf-8-sig"))
    deterministic_baseline = {
        stage: float(value)
        for stage, value in baseline_doc.get("stages", {}).items()
        if stage in current
    }
    regressed = check_regression(deterministic_baseline, current)
    assert regressed == (), f"stages below baseline: {regressed}"
    # And the baseline actually gates these stages — an empty baseline gates nothing.
    assert {"chunking", "entity_resolution", "conflict_detection"} <= set(deterministic_baseline)
