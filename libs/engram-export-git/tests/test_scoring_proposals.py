"""M5 spine intents through the real stack: confirm/contradict merge, undo via
MemoryConfidenceRestored, direct spine commands, and replay determinism across
the whole lifecycle (ADR-0019)."""

import json
from pathlib import Path

import pytest
from export_harness import ASSISTANT, USER, Space, build_space

from engram_core.application.commands import drafts as d
from engram_core.application.dto import CreateMemoryInput
from engram_core.domain import scoring
from engram_core.domain.values import MemoryId, MemoryKind


@pytest.fixture
def space(tmp_path: Path) -> Space:
    return build_space(tmp_path / "engram.db")


def _fact(space: Space, statement: str = "User prefers dark mode") -> MemoryId:
    return space.commands.create_memory(
        CreateMemoryInput(
            kind=MemoryKind.FACT,
            title=statement,
            content="",
            attributes={"statement": statement},
        ),
        USER,
    )


def _log_view(space: Space) -> list[tuple[str, str, int, str]]:
    return [
        (str(e.stream_id), e.event_type, e.stream_seq, json.dumps(str(e.payload)))
        for e in space.store.read_all()
    ]


@pytest.mark.integration
def test_direct_confirm_contradict_move_confidence_by_policy(space: Space) -> None:
    fact_id = _fact(space)
    before = space.query.get(fact_id).confidence  # user-stated prior 0.95

    space.commands.confirm_memory(fact_id, "double-checked", USER)
    confirmed = space.query.get(fact_id)
    assert confirmed.confidence == pytest.approx(
        scoring.confirm_confidence(before, scoring.CONFIRM_WEIGHT_USER)
    )
    assert confirmed.last_confirmed_at is not None

    other = _fact(space, "User prefers light mode")
    space.commands.contradict_memory(fact_id, other, "they disagree", ASSISTANT)
    contradicted = space.query.get(fact_id)
    assert contradicted.confidence == pytest.approx(
        scoring.contradict_confidence(confirmed.confidence, scoring.CONTRADICT_WEIGHT_ASSISTANT)
    )
    assert any(
        str(link.target_id) == str(other) and link.relation == "contradicts"
        for link in contradicted.links
    )


@pytest.mark.integration
def test_importance_and_access_signals_reach_the_read_side(space: Space) -> None:
    fact_id = _fact(space)
    space.commands.adjust_importance(fact_id, pinned=True, user_weight=0.8, provenance=USER)
    space.commands.record_access(fact_id, "recall", ASSISTANT)
    space.commands.record_access(fact_id, "recall", ASSISTANT)
    model = space.query.get(fact_id)
    assert model.pinned and model.user_weight == 0.8
    assert model.access_count == 2 and model.last_accessed_at is not None
    assert model.retention_score > 0.0

    space.commands.adjust_importance(fact_id, clear_user_weight=True, provenance=USER)
    assert space.query.get(fact_id).user_weight is None


@pytest.mark.integration
def test_contradict_proposal_merges_with_assistant_weight_and_undoes_exactly(
    space: Space,
) -> None:
    fact_id = _fact(space)
    new_id = _fact(space, "User prefers OLED dark mode")
    target = space.query.get(fact_id)
    before_confidence = target.confidence
    before_confirmed_at = target.last_confirmed_at

    proposal_id = space.proposals.open_proposal(
        "pipeline: contradiction found",
        "the conversation disputes an existing fact",
        [
            d.to_dict(
                d.ContradictMemoryDraft(
                    memory_id=fact_id,
                    base_version=target.version,
                    contradicting_id=new_id,
                    note="same context, newer statement",
                )
            )
        ],
        ASSISTANT,
    )
    space.proposals.approve_proposal(proposal_id, "reviewed", USER)
    appended = space.proposals.merge_proposal(proposal_id, USER)
    assert len(appended) == 2  # MemoryContradicted + the contradicts edge

    merged = space.query.get(fact_id)
    # Proposals are automation's door: the assistant weight applies even though
    # a user merged it (ADR-0019 §1).
    assert merged.confidence == pytest.approx(
        scoring.contradict_confidence(before_confidence, scoring.CONTRADICT_WEIGHT_ASSISTANT)
    )

    log_before_undo = len(_log_view(space))
    space.proposals.undo_proposal(proposal_id, "changed my mind", USER)
    restored = space.query.get(fact_id)
    assert restored.confidence == pytest.approx(before_confidence)
    assert restored.last_confirmed_at == before_confirmed_at
    assert not any(link.relation == "contradicts" for link in restored.links)
    # History grew — nothing was erased.
    assert len(_log_view(space)) > log_before_undo
    types = [e.event_type for e in space.store.read_all()]
    assert "MemoryConfidenceRestored" in types  # ADR-0019 §2, its only producer


@pytest.mark.integration
def test_confirm_proposal_round_trip(space: Space) -> None:
    fact_id = _fact(space)
    target = space.query.get(fact_id)
    proposal_id = space.proposals.open_proposal(
        "confirm it",
        "",
        [d.to_dict(d.ConfirmMemoryDraft(memory_id=fact_id, base_version=target.version))],
        ASSISTANT,
    )
    space.proposals.approve_proposal(proposal_id, None, USER)
    space.proposals.merge_proposal(proposal_id, USER)
    confirmed = space.query.get(fact_id)
    assert confirmed.confidence == pytest.approx(
        scoring.confirm_confidence(target.confidence, scoring.CONFIRM_WEIGHT_ASSISTANT)
    )
    space.proposals.undo_proposal(proposal_id, None, USER)
    undone = space.query.get(fact_id)
    assert undone.confidence == pytest.approx(target.confidence)
    assert undone.last_confirmed_at is None


@pytest.mark.integration
def test_replay_determinism_across_the_scoring_lifecycle(space: Space) -> None:
    """The M1 invariant, extended to M5's events: rebuild lands on identical rows."""
    fact_id = _fact(space)
    other = _fact(space, "User prefers light mode")
    space.commands.confirm_memory(fact_id, None, USER)
    space.commands.contradict_memory(fact_id, other, None, ASSISTANT)
    space.commands.adjust_importance(fact_id, pinned=True, user_weight=0.6, provenance=USER)
    space.commands.record_access(fact_id, "recall", ASSISTANT)
    target = space.query.get(fact_id)
    proposal_id = space.proposals.open_proposal(
        "confirm again",
        "",
        [d.to_dict(d.ConfirmMemoryDraft(memory_id=fact_id, base_version=target.version))],
        ASSISTANT,
    )
    space.proposals.approve_proposal(proposal_id, None, USER)
    space.proposals.merge_proposal(proposal_id, USER)
    space.proposals.undo_proposal(proposal_id, None, USER)

    def snapshot() -> dict[str, object]:
        model = space.query.get(fact_id)
        return {
            "confidence": round(model.confidence, 12),
            "last_confirmed_at": model.last_confirmed_at,
            "pinned": model.pinned,
            "user_weight": model.user_weight,
            "access_count": model.access_count,
            "links": tuple(sorted((str(edge.target_id), edge.relation) for edge in model.links)),
            "version": model.version,
        }

    before = snapshot()
    log_before = _log_view(space)
    space.rebuild()
    assert snapshot() == before
    assert _log_view(space) == log_before  # replay reads; it never writes
