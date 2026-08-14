"""Phase 0.75 contract tests: prompt registry rules, the fake provider, and the
regression gate — the pieces that must hold before any AI code exists."""

import pytest
from engram_intelligence.evals import check_regression
from engram_intelligence.prompts.registry import (
    PromptRegistry,
    PromptTemplate,
    load_library,
    verify_library_lock,
)
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
def test_prompt_fingerprint_changes_iff_behavior_relevant_content_changes() -> None:
    base = _template(1)
    same_content_different_frontmatter_order = PromptTemplate(
        name=base.name,
        version=base.version,
        author=base.author,
        stage=base.stage,
        body=base.body,
    )
    assert same_content_different_frontmatter_order.fingerprint == base.fingerprint

    edited_body = PromptTemplate(
        name=base.name, version=base.version, author=base.author, stage=base.stage, body="new text"
    )
    assert edited_body.fingerprint != base.fingerprint  # this is the P1 defect: same
    # version, different behavior — nothing about PromptRegistry.register() alone
    # would ever catch that; the fingerprint is what makes it detectable.

    bumped_version = _template(2)
    assert bumped_version.fingerprint != base.fingerprint  # a legitimate new version
    # also changes the fingerprint — expected, and exactly why the lock file keys
    # on qualified_name (name@version), not name alone.


@pytest.mark.unit
def test_shipped_prompt_library_matches_its_committed_lock() -> None:
    """ADR-0013: 'shipped versions are never edited in place.' Nothing enforced
    that until this test — PromptRegistry.register() only rejects a *duplicate*
    (name, version) key; it has no way to notice that an already-shipped
    version's file changed underneath it. This is the P1 fix: a committed
    content fingerprint per version (library.lock.json), verified here.

    If this fails: either an already-shipped prompt was edited in place —
    revert it, or bump its version — or a deliberate new version was added and
    the lock file wasn't regenerated alongside it (see
    ``engram_intelligence.prompts.registry.library_fingerprints``).
    """
    mismatches = verify_library_lock(load_library())
    assert mismatches == (), "\n".join(mismatches)


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
