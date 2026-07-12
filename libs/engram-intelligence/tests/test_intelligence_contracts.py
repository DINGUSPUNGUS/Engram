"""Phase 0.75 contract tests: prompt registry rules, the fake provider, and the
regression gate — the pieces that must hold before any AI code exists."""

import pytest
from engram_intelligence.evals import check_regression
from engram_intelligence.prompts.registry import PromptRegistry, PromptTemplate
from engram_intelligence.provider import FakeProvider, LLMRequest

from engram_core.domain.errors import ValidationError


def _template(version: int) -> PromptTemplate:
    return PromptTemplate(
        name="evidence-extraction",
        version=version,
        author="test",
        stage="evidence_extraction",
        body="extract things from {chunk}",
    )


@pytest.mark.unit
def test_prompt_versions_are_append_only() -> None:
    registry = PromptRegistry()
    registry.register(_template(1))
    with pytest.raises(ValidationError):
        registry.register(_template(1))  # shipped versions are immutable (ADR-0013)
    registry.register(_template(2))
    assert registry.versions("evidence-extraction") == (1, 2)


@pytest.mark.unit
def test_latest_version_resolution_and_audit_name() -> None:
    registry = PromptRegistry()
    registry.register(_template(1))
    registry.register(_template(3))
    latest = registry.get("evidence-extraction")
    assert latest.version == 3
    assert latest.qualified_name == "evidence-extraction@3"
    with pytest.raises(ValidationError):
        registry.get("nonexistent")


@pytest.mark.unit
def test_empty_prompt_bodies_rejected() -> None:
    with pytest.raises(ValidationError):
        PromptTemplate(name="x", version=1, author="t", stage="s", body="   ")


@pytest.mark.unit
def test_fake_provider_round_trip() -> None:
    provider = FakeProvider(responses={"evidence-extraction": "[]"})
    response = provider.complete(
        LLMRequest(
            prompt_name="evidence-extraction",
            prompt_version=1,
            rendered_prompt="extract things from hello",
            json_output=True,
        )
    )
    assert response.text == "[]"
    assert response.model_id == "fake"  # provenance only — never branch on it


@pytest.mark.unit
def test_regression_gate() -> None:
    baseline = {"evidence_extraction": 0.80, "entity_resolution": 0.70}
    assert (
        check_regression(baseline, {"evidence_extraction": 0.85, "entity_resolution": 0.70}) == ()
    )
    regressed = check_regression(baseline, {"evidence_extraction": 0.75, "entity_resolution": 0.70})
    assert regressed == ("evidence_extraction",)
    # A stage missing from the current run is a regression, not a pass.
    assert check_regression(baseline, {"evidence_extraction": 0.85}) == ("entity_resolution",)
    # Tolerance permits noise, not decline.
    assert (
        check_regression(
            baseline, {"evidence_extraction": 0.79, "entity_resolution": 0.70}, tolerance=0.02
        )
        == ()
    )
