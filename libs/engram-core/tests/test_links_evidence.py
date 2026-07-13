"""Aggregate rules for the M3 additions: tier-1 links and spine evidence."""

from datetime import UTC, datetime

import pytest

from engram_core.domain import events as ev
from engram_core.domain.errors import ValidationError
from engram_core.domain.kinds import FactAttributes, build_kind_registry
from engram_core.domain.memory import Memory
from engram_core.domain.values import (
    EvidenceRef,
    EvidenceType,
    Link,
    LinkRelation,
    MemoryId,
    MemoryKind,
    Slug,
    new_memory_id,
)
from engram_events import EventEnvelope, Provenance

KINDS = build_kind_registry()


def _envelope(stream_id: MemoryId, seq: int, payload: object) -> EventEnvelope:
    return EventEnvelope(
        event_id=new_memory_id(),
        stream_id=stream_id,
        stream_seq=seq,
        event_type=type(payload).__name__,
        schema_version=1,
        payload=payload,
        occurred_at=datetime.now(UTC),
        provenance=Provenance(actor="user"),
        global_seq=seq,
    )


def _fact() -> Memory:
    memory_id = new_memory_id()
    (created,) = Memory.decide_create(
        memory_id,
        MemoryKind.FACT,
        Slug("f-1"),
        "a fact",
        "",
        FactAttributes(statement="s"),
        KINDS,
    )
    return Memory.fold([_envelope(memory_id, 1, created)], KINDS)


@pytest.mark.unit
class TestLinks:
    def test_link_produces_event_and_folds_into_state(self) -> None:
        memory = _fact()
        target = new_memory_id()
        (linked,) = memory.decide_link(Link(target, LinkRelation.ABOUT))
        assert isinstance(linked, ev.MemoryLinked)
        after = memory.evolve(_envelope(memory.id, 2, linked))
        assert after.links == (Link(target, LinkRelation.ABOUT),)

    def test_duplicate_link_is_a_no_op(self) -> None:
        memory = _fact()
        target = new_memory_id()
        (linked,) = memory.decide_link(Link(target, LinkRelation.ABOUT))
        after = memory.evolve(_envelope(memory.id, 2, linked))
        assert after.decide_link(Link(target, LinkRelation.ABOUT)) == ()

    def test_self_link_rejected(self) -> None:
        memory = _fact()
        with pytest.raises(ValidationError, match="itself"):
            memory.decide_link(Link(memory.id, LinkRelation.RELATES_TO))

    def test_unlink_folds_out_of_state(self) -> None:
        memory = _fact()
        target = new_memory_id()
        (linked,) = memory.decide_link(Link(target, LinkRelation.ABOUT))
        after = memory.evolve(_envelope(memory.id, 2, linked))
        gone = after.evolve(
            _envelope(memory.id, 3, ev.MemoryUnlinked(target_id=target, relation="about"))
        )
        assert gone.links == ()


@pytest.mark.unit
class TestEvidence:
    def test_evidence_appends_and_folds(self) -> None:
        memory = _fact()
        ref = EvidenceRef(EvidenceType.QUOTE, "said so", note="ctx")
        (added,) = memory.decide_add_evidence(ref)
        assert isinstance(added, ev.MemoryEvidenceAdded)
        after = memory.evolve(_envelope(memory.id, 2, added))
        assert after.evidence == (ref,)

    def test_evidence_is_append_only_never_replaced(self) -> None:
        memory = _fact()
        first = EvidenceRef(EvidenceType.QUOTE, "one")
        second = EvidenceRef(EvidenceType.URI, "https://example.com")
        state = memory
        for seq, ref in ((2, first), (3, second)):
            (payload,) = state.decide_add_evidence(ref)
            state = state.evolve(_envelope(memory.id, seq, payload))
        assert state.evidence == (first, second)
