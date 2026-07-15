"""Proposal lifecycle rules and the draft-intent wire format (ADR-0018)."""

from datetime import UTC, datetime
from uuid import UUID

import pytest

from engram_core.application.commands import drafts as d
from engram_core.domain import events as ev
from engram_core.domain.errors import ConflictError, ValidationError
from engram_core.domain.proposal import Proposal, ProposalStatus
from engram_core.domain.values import new_proposal_id
from engram_events import EventEnvelope, Provenance, new_uuid7

DRAFT = {
    "draft_schema_version": 2,
    "op": "edit_memory",
    "memory_id": "0198aaaa-0000-7000-8000-000000000001",
    "base_version": 3,
    "title": "new title",
}


def _envelope(stream_id: object, seq: int, payload: object) -> EventEnvelope:
    return EventEnvelope(
        event_id=new_uuid7(),
        stream_id=stream_id,  # type: ignore[arg-type]
        stream_seq=seq,
        event_type=type(payload).__name__,
        schema_version=1,
        payload=payload,
        occurred_at=datetime.now(UTC),
        provenance=Provenance(actor="user"),
        global_seq=seq,
    )


def _pending() -> Proposal:
    proposal_id = new_proposal_id()
    (opened,) = Proposal.decide_open(proposal_id, "t", "d", [DRAFT])
    return Proposal.fold([_envelope(proposal_id, 1, opened)])


@pytest.mark.unit
class TestLifecycle:
    def test_open_requires_title_and_drafts(self) -> None:
        with pytest.raises(ValidationError, match="title"):
            Proposal.decide_open(new_proposal_id(), "  ", "", [DRAFT])
        with pytest.raises(ValidationError, match="at least one"):
            Proposal.decide_open(new_proposal_id(), "t", "", [])

    def test_approve_then_merge_then_undo(self) -> None:
        proposal = _pending()
        assert proposal.status is ProposalStatus.PENDING

        (approved,) = proposal.decide_approve("lgtm")
        proposal = proposal.evolve(_envelope(proposal.id, 2, approved))
        assert proposal.status is ProposalStatus.APPROVED
        assert proposal.review_note == "lgtm"

        event_id = new_uuid7()
        (merged,) = proposal.decide_merge((event_id,))
        proposal = proposal.evolve(_envelope(proposal.id, 3, merged))
        assert proposal.status is ProposalStatus.MERGED
        assert proposal.merged_event_ids == (event_id,)

        (undone,) = proposal.decide_undo((new_uuid7(),), note="mistake")
        proposal = proposal.evolve(_envelope(proposal.id, 4, undone))
        assert proposal.status is ProposalStatus.UNDONE

    def test_merge_requires_approval(self) -> None:
        with pytest.raises(ConflictError, match="only approved"):
            _pending().decide_merge((new_uuid7(),))

    def test_review_is_terminal_per_branch(self) -> None:
        proposal = _pending()
        (rejected,) = proposal.decide_reject("nope")
        proposal = proposal.evolve(_envelope(proposal.id, 2, rejected))
        assert proposal.status is ProposalStatus.REJECTED
        with pytest.raises(ConflictError, match="already rejected"):
            proposal.decide_approve()
        with pytest.raises(ConflictError, match="only approved"):
            proposal.decide_merge(())
        with pytest.raises(ConflictError, match="only merged"):
            proposal.decide_undo(())

    def test_fold_requires_opened_first(self) -> None:
        with pytest.raises(ValidationError, match="ProposalOpened"):
            Proposal.fold([_envelope(new_proposal_id(), 1, ev.ProposalApproved())])


@pytest.mark.unit
class TestDraftWireFormat:
    def test_v2_round_trip(self) -> None:
        intent = d.parse_draft(DRAFT)
        assert isinstance(intent, d.EditMemoryDraft)
        assert intent.base_version == 3
        assert d.parse_draft(d.to_dict(intent)) == intent

    def test_every_op_round_trips(self) -> None:
        memory_id = UUID("0198aaaa-0000-7000-8000-000000000001")
        target_id = UUID("0198aaaa-0000-7000-8000-000000000002")
        intents: list[d.DraftIntent] = [
            d.CreateMemoryDraft(
                memory_id=memory_id,
                kind="fact",
                slug="s-1",
                title="t",
                content="c",
                attributes={"statement": "x"},
                attributes_schema_version=1,
                tags=("a",),
                confidence=0.8,
                lifetime_policy="standard",
                lifetime_until=None,
                visibility="shared",
            ),
            d.TagMemoryDraft(memory_id=memory_id, base_version=1, add=("x",), remove=()),
            d.UpdateAttributesDraft(
                memory_id=memory_id, base_version=1, changes={"statement": "y"}
            ),
            d.LinkDraft(source_id=memory_id, target_id=target_id, relation="about", base_version=1),
            d.UnlinkDraft(
                source_id=memory_id, target_id=target_id, relation="about", base_version=1
            ),
            d.AddEvidenceDraft(
                memory_id=memory_id, base_version=1, evidence_type="quote", value="v"
            ),
            d.SetVisibilityDraft(memory_id=memory_id, base_version=1, visibility="private"),
            d.SetLifetimeDraft(memory_id=memory_id, base_version=1, lifetime_policy="permanent"),
        ]
        for intent in intents:
            assert d.parse_draft(d.to_dict(intent)) == intent

    def test_v1_event_shaped_drafts_upcast(self) -> None:
        v1 = {
            "draft_id": "x",
            "stream_id": "0198aaaa-0000-7000-8000-000000000001",
            "event_type": "MemoryCreated",
            "schema_version": 1,
            "payload": {
                "memory_id": "0198aaaa-0000-7000-8000-000000000001",
                "kind": "fact",
                "slug": "s-1",
                "title": "t",
                "content": "",
                "attributes": {"statement": "x"},
                "attributes_schema_version": 1,
                "tags": [],
                "confidence": 0.8,
                "lifetime_policy": "standard",
                "lifetime_until": None,
                "visibility": "shared",
            },
        }
        intent = d.parse_draft(v1)
        assert isinstance(intent, d.CreateMemoryDraft)
        assert intent.base_version == 0
        assert intent.title == "t"

    def test_unknown_op_and_version_rejected(self) -> None:
        with pytest.raises(ValidationError, match="unknown draft op"):
            d.parse_draft({"draft_schema_version": 2, "op": "explode"})
        with pytest.raises(ValidationError, match="draft schema version"):
            d.parse_draft({"draft_schema_version": 99, "op": "edit_memory"})

    def test_parse_all_reports_every_problem(self) -> None:
        with pytest.raises(ValidationError) as excinfo:
            d.parse_all([{"op": "bad1"}, DRAFT, {"op": "bad2"}])
        assert "draft #1" in str(excinfo.value)
        assert "draft #3" in str(excinfo.value)
