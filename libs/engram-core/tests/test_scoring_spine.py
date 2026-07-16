"""The scoring spine (M5, ADR-0019): confirm/contradict/importance decide+fold,
the policy formulas, and the wire form of the new draft intents."""

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from engram_core.application.commands import drafts as d
from engram_core.domain import events as ev
from engram_core.domain import scoring
from engram_core.domain.errors import ValidationError
from engram_core.domain.kinds import FactAttributes, build_kind_registry
from engram_core.domain.memory import Memory
from engram_core.domain.values import LinkRelation, MemoryKind, Slug, new_memory_id
from engram_events import EventEnvelope, Provenance, new_uuid7

KINDS = build_kind_registry()
NOW = datetime(2026, 7, 15, 12, 0, 0, tzinfo=UTC)


def envelope(stream_id: Any, seq: int, payload: object) -> EventEnvelope:
    return EventEnvelope(
        event_id=new_uuid7(),
        stream_id=stream_id,
        stream_seq=seq,
        event_type=type(payload).__name__,
        schema_version=1,
        payload=payload,
        occurred_at=NOW,
        provenance=Provenance(actor="user"),
    )


def fact(confidence: float = 0.6) -> Memory:
    memory_id = new_memory_id()
    payloads = Memory.decide_create(
        memory_id,
        MemoryKind.FACT,
        Slug("a-fact"),
        "a fact",
        "",
        FactAttributes(statement="a fact"),
        KINDS,
        confidence=confidence,
    )
    return Memory.fold([envelope(memory_id, 1, payloads[0])], KINDS)


# ---------------------------------------------------------------------------
# Policy formulas (memory-model.md §5, §7)
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_confidence_formulas_match_the_model() -> None:
    assert scoring.confirm_confidence(0.6, 0.5) == pytest.approx(0.8)
    assert scoring.contradict_confidence(0.8, 0.5) == pytest.approx(0.4)
    assert scoring.confirm_confidence(1.0, 0.9) == 1.0  # clamped
    assert scoring.contradict_confidence(0.0, 0.9) == 0.0


@pytest.mark.unit
def test_weights_resolve_user_above_assistant() -> None:
    assert scoring.confirm_weight_for("user") > scoring.confirm_weight_for("claude")
    assert scoring.contradict_weight_for("user") > scoring.contradict_weight_for("chatgpt")


@pytest.mark.unit
def test_effective_confidence_halves_per_half_life() -> None:
    config = scoring.ScoringConfig()
    half_life = config.half_life_days[MemoryKind.FACT]
    anchor = NOW - timedelta(days=half_life)
    assert scoring.effective_confidence(0.8, MemoryKind.FACT, anchor, NOW, config) == pytest.approx(
        0.4
    )


@pytest.mark.unit
def test_retention_score_rises_with_signals() -> None:
    config = scoring.ScoringConfig()
    quiet = scoring.retention_score(
        kind=MemoryKind.FACT,
        effective_confidence=0.5,
        last_accessed_at=None,
        access_count=0,
        link_degree=0,
        user_weight=None,
        now=NOW,
        config=config,
    )
    busy = scoring.retention_score(
        kind=MemoryKind.FACT,
        effective_confidence=0.5,
        last_accessed_at=NOW - timedelta(days=1),
        access_count=20,
        link_degree=4,
        user_weight=0.8,
        now=NOW,
        config=config,
    )
    assert busy > quiet


@pytest.mark.unit
def test_candidate_importance_is_policy_not_magic() -> None:
    base = scoring.candidate_importance(MemoryKind.FACT)
    assert base == scoring.IMPORTANCE_KIND_BASE[MemoryKind.FACT]
    boosted = scoring.candidate_importance(
        MemoryKind.FACT, evidence_count=2, link_count=1, contradicts_existing=True
    )
    assert boosted == pytest.approx(
        base
        + 2 * scoring.IMPORTANCE_EVIDENCE_BOOST
        + scoring.IMPORTANCE_LINK_BOOST
        + scoring.IMPORTANCE_CONTRADICTION_BOOST
    )
    assert scoring.candidate_importance(MemoryKind.PERSON, evidence_count=99, link_count=99) <= 1.0


# ---------------------------------------------------------------------------
# Aggregate: decide + fold
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_confirm_raises_confidence_and_resets_staleness_anchor() -> None:
    memory = fact(confidence=0.6)
    (payload,) = memory.decide_confirm(0.5, note="checked")
    assert isinstance(payload, ev.MemoryConfirmed)
    assert payload.weight == 0.5  # the resolved signal is recorded (ADR-0019)
    after = memory.evolve(envelope(memory.id, 2, payload))
    assert after.confidence == pytest.approx(0.8)
    assert after.last_confirmed_at == NOW


@pytest.mark.unit
def test_contradict_decays_confidence_and_links_the_disputer() -> None:
    memory = fact(confidence=0.8)
    other = new_memory_id()
    payloads = memory.decide_contradict(0.5, other, note="disputed")
    assert [type(p).__name__ for p in payloads] == ["MemoryContradicted", "MemoryLinked"]
    linked = payloads[1]
    assert isinstance(linked, ev.MemoryLinked)
    assert linked.relation == LinkRelation.CONTRADICTS.value
    state = memory
    for offset, payload in enumerate(payloads):
        state = state.evolve(envelope(memory.id, 2 + offset, payload))
    assert state.confidence == pytest.approx(0.4)
    assert state.last_confirmed_at is None  # contradiction never vouches

    with pytest.raises(ValidationError):
        memory.decide_contradict(0.5, memory.id)  # self-contradiction
    with pytest.raises(ValidationError):
        memory.decide_confirm(1.5)  # weight out of range


@pytest.mark.unit
def test_confidence_restored_is_a_pure_state_reset() -> None:
    memory = fact(confidence=0.6)
    confirmed = memory.evolve(envelope(memory.id, 2, ev.MemoryConfirmed(weight=0.5)))
    restored = confirmed.evolve(
        envelope(
            memory.id,
            3,
            ev.MemoryConfidenceRestored(confidence=0.6, last_confirmed_at=None, reason="undo"),
        )
    )
    assert restored.confidence == 0.6
    assert restored.last_confirmed_at is None
    assert restored.version == 3  # history grew; state returned


@pytest.mark.unit
def test_importance_adjustment_elides_noops_and_clears_weights() -> None:
    memory = fact()
    assert memory.decide_adjust_importance(pinned=False) == ()  # already unpinned
    (payload,) = memory.decide_adjust_importance(pinned=True, user_weight=0.7)
    assert isinstance(payload, ev.MemoryImportanceAdjusted)
    weighted = memory.evolve(envelope(memory.id, 2, payload))
    assert weighted.importance.pinned and weighted.importance.user_weight == 0.7

    (cleared,) = weighted.decide_adjust_importance(clear_user_weight=True)
    assert isinstance(cleared, ev.MemoryImportanceAdjusted)
    assert cleared.clear_user_weight and cleared.user_weight is None
    unweighted = weighted.evolve(envelope(memory.id, 3, cleared))
    assert unweighted.importance.user_weight is None
    assert unweighted.importance.pinned  # untouched

    with pytest.raises(ValidationError):
        memory.decide_adjust_importance()  # requests nothing
    with pytest.raises(ValidationError):
        memory.decide_adjust_importance(user_weight=0.5, clear_user_weight=True)
    with pytest.raises(ValidationError):
        memory.decide_adjust_importance(user_weight=1.5)


# ---------------------------------------------------------------------------
# Draft intents: wire form
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_confirm_and_contradict_drafts_round_trip() -> None:
    memory_id = new_memory_id()
    other = new_memory_id()
    confirm = d.ConfirmMemoryDraft(memory_id=memory_id, base_version=3, note="looks right")
    contradict = d.ContradictMemoryDraft(
        memory_id=memory_id, base_version=3, contradicting_id=other, note="clashes"
    )
    for intent in (confirm, contradict):
        record = d.to_dict(intent)
        assert record["draft_schema_version"] == d.DRAFT_SCHEMA_VERSION
        assert d.parse_draft(record) == intent
    assert d.to_dict(confirm)["op"] == "confirm_memory"
    assert d.to_dict(contradict)["op"] == "contradict_memory"

    bare = d.ContradictMemoryDraft(memory_id=memory_id, base_version=None)
    assert d.parse_draft(d.to_dict(bare)) == bare  # None contradicting_id survives
