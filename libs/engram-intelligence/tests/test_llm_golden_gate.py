"""The LLM-backed half of the golden suite (ADR-0014): ``evidence_extraction``
and ``candidate_generation``, gated separately from the deterministic stages.

``test_golden_gate.py`` covers chunking/entity_resolution/conflict_detection —
those "run in CI always" per ADR-0014 and require no network. The two stages
here need a real model; the ADR is explicit that they "run when a provider is
configured (locally, or CI with a pinned local model)" — a condition, not an
unconditional requirement — and ``evaluations/results/baseline.json`` records
that until a baseline is actually measured "their evaluators exist but gate
nothing." Before this file, that measurement had no path to happen at all:
``evaluators.llm_evaluators`` had zero callers anywhere in the tree, so no one
— not CI, not a developer with Ollama running — could ever exercise them.

This gives them exactly one caller, opt-in and skip-by-default:

- Unset ``ENGRAM_LLM_EVAL`` (the ordinary case, including every CI run today):
  skipped at collection time. No network attempt is made — satisfies ADR-0014
  and the M9 audit constraint that the ordinary suite never depend on Ollama.
- ``ENGRAM_LLM_EVAL=1`` with a reachable Ollama endpoint (``ENGRAM_LLM_MODEL``,
  default matches docs/intelligence.md): runs for real, against the pinned
  determinism settings ``OllamaProvider`` already applies (temperature 0,
  fixed seed), and gates on ``baseline.json`` as soon as that file records a
  measured LLM entry — exactly the mechanism ``test_golden_gate.py`` uses for
  the deterministic stages, extended to these two.
"""

import json
import os
from pathlib import Path

import httpx
import pytest
from engram_intelligence.evals import check_regression, load_golden_cases
from engram_intelligence.evaluators import llm_evaluators, run_suite
from engram_intelligence.prompts.registry import load_library
from engram_intelligence.providers.ollama import OllamaProvider

from engram_core.domain.kinds import build_kind_registry

_REPO_ROOT = Path(__file__).resolve().parents[3]
GOLDEN_DIR = _REPO_ROOT / "evaluations" / "golden"
BASELINE_PATH = _REPO_ROOT / "evaluations" / "results" / "baseline.json"
_DEFAULT_BASE_URL = "http://127.0.0.1:11434"  # matches providers/ollama.py's own default
_DEFAULT_MODEL = "llama3.2:1b"

if not os.environ.get("ENGRAM_LLM_EVAL"):
    pytest.skip(
        "LLM-backed golden stages are opt-in (ENGRAM_LLM_EVAL=1) — ADR-0014 runs"
        " them only when a provider is configured, never as part of the ordinary,"
        " network-free suite.",
        allow_module_level=True,
    )

_BASE_URL = os.environ.get("ENGRAM_OLLAMA_URL", _DEFAULT_BASE_URL)
try:
    httpx.get(_BASE_URL, timeout=2.0).raise_for_status()
except httpx.HTTPError as exc:
    pytest.skip(
        f"ENGRAM_LLM_EVAL=1 but no Ollama reachable at {_BASE_URL}: {exc}",
        allow_module_level=True,
    )


@pytest.mark.integration
def test_llm_stages_meet_the_committed_baseline() -> None:
    kinds = build_kind_registry()
    prompts = load_library()
    provider = OllamaProvider(os.environ.get("ENGRAM_LLM_MODEL", _DEFAULT_MODEL))
    cases = load_golden_cases(GOLDEN_DIR)

    current, scores = run_suite(cases, llm_evaluators(provider, prompts, kinds))
    failures = [s for s in scores if not s.passed]
    assert not failures, "; ".join(f"{s.stage}/{s.case_id}: {s.detail}" for s in failures)

    baseline_doc = json.loads(BASELINE_PATH.read_text(encoding="utf-8-sig"))
    llm_baseline = {
        stage: float(value)
        for stage, value in baseline_doc.get("stages", {}).items()
        if stage in current
    }
    if not llm_baseline:
        pytest.skip(
            "baseline.json has no measured LLM-stage entries yet — this run's scores"
            f" are the candidate for the first one: {current}"
        )
    regressed = check_regression(llm_baseline, current)
    assert regressed == (), f"stages below baseline: {regressed}"
