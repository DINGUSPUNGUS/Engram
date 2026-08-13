"""End to end through the reference plugin (ADR-0024 "Reference plugin"):

    capability → existing read/application port → candidate knowledge →
    Proposal → human approval → Merge → provenance

Plus the two behavioral guarantees the milestone requires of *any* plugin:
self-approval/self-merge is impossible, and output is deterministic.
"""

import json
from pathlib import Path
from uuid import UUID

import pytest
from plugins_harness import PluginSpace, build_plugin_space

from engram_core.domain.errors import ConflictError
from engram_core.domain.values import MemoryId, MemoryKind, ProposalId
from engram_events import Provenance
from engram_plugins.contract import PluginContext
from engram_plugins.plugins.reference_url_evidence import PLUGIN_ID, ReferenceUrlEvidencePlugin

HUMAN = Provenance(actor="user")


def _seed(space: PluginSpace) -> MemoryId:
    return space.add_memory(
        MemoryKind.FACT,
        "engram repo",
        "The canonical repo lives at https://github.com/example/engram, see it.",
        statement="engram repo location",
    )


def test_full_workflow_propose_review_merge_provenance(tmp_path: Path) -> None:
    space = build_plugin_space(tmp_path / "engram.db")
    memory_id = _seed(space)
    space.rebuild()

    plugin = ReferenceUrlEvidencePlugin()
    space.registry.register(plugin)
    space.registry.enable(PLUGIN_ID)

    result = space.registry.run(PLUGIN_ID, space.gateway, PluginContext(source="test"))
    assert result.ok is True
    assert result.candidate_count == 1
    assert result.proposal_id is not None
    proposal_id = ProposalId(UUID(result.proposal_id))

    # Nothing became memory yet: the plugin's write is a proposal only.
    before = space.memory_queries.get_memory(memory_id)
    assert before.evidence == ()

    detail = space.proposal_queries.get_proposal(proposal_id)
    assert detail.status == "pending"

    # A plugin cannot approve or merge its own proposal — those verbs belong
    # to a human/application surface only (ADR-0024 §4).
    with pytest.raises(ConflictError):
        space.proposals.merge_proposal(proposal_id, HUMAN)

    space.proposals.approve_proposal(proposal_id, "looks right", HUMAN)
    space.proposals.merge_proposal(proposal_id, HUMAN)

    after = space.memory_queries.get_memory(memory_id)
    assert len(after.evidence) == 1
    assert after.evidence[0].value == "https://github.com/example/engram"
    assert after.evidence[0].evidence_type == "uri"

    # The merged memory event itself carries the human reviewer's provenance
    # (ADR-0018: merge is the human/application surface's own act) — the
    # plugin's provenance rides the *proposal's* ProposalOpened event, exactly
    # where the M5 pipeline's explanation already lives (ADR-0019 §3).
    from engram_core.application.queries.timeline_queries import TimelineQueryService

    memory_timeline = TimelineQueryService(space.query).memory_timeline(memory_id)
    added = next(e for e in memory_timeline if e.event_type == "MemoryEvidenceAdded")
    assert added.actor == "user"

    proposal_timeline = space.proposal_queries.timeline(proposal_id)
    opened = next(e for e in proposal_timeline if e.event_type == "ProposalOpened")
    assert opened.actor == f"plugin:{PLUGIN_ID}"
    payload = json.loads(opened.detail or "{}")["plugin"]
    assert payload["plugin_id"] == PLUGIN_ID
    assert payload["plugin_version"] == "1.0.0"
    assert payload["capability"] == "proposal_submit"
    assert payload["run_id"] is not None


def test_run_after_removal_is_impossible_but_history_stays_readable(tmp_path: Path) -> None:
    space = build_plugin_space(tmp_path / "engram.db")
    memory_id = _seed(space)
    space.rebuild()

    plugin = ReferenceUrlEvidencePlugin()
    space.registry.register(plugin)
    space.registry.enable(PLUGIN_ID)
    result = space.registry.run(PLUGIN_ID, space.gateway, PluginContext())
    proposal_id = ProposalId(UUID(str(result.proposal_id)))
    space.proposals.approve_proposal(proposal_id, None, HUMAN)
    space.proposals.merge_proposal(proposal_id, HUMAN)

    space.registry.remove(PLUGIN_ID)
    assert space.registry.list() == ()

    # Existing memory remains fully valid and readable after removal.
    memory = space.memory_queries.get_memory(memory_id)
    assert len(memory.evidence) == 1

    from engram_core.domain.errors import NotFoundError

    with pytest.raises(NotFoundError):
        space.registry.run(PLUGIN_ID, space.gateway, PluginContext())


def test_deterministic_output_for_identical_state(tmp_path: Path) -> None:
    """Same memory state, same config ⇒ same candidate drafts, in both runs
    (ADR-0024's determinism requirement — no clock/network/AI involved)."""
    results: list[tuple[str, ...]] = []
    for db_name in ("a.db", "b.db"):
        space = build_plugin_space(tmp_path / db_name)
        _seed(space)
        space.rebuild()
        plugin = ReferenceUrlEvidencePlugin()
        space.registry.register(plugin)
        space.registry.enable(PLUGIN_ID)
        outcome = space.registry.run(
            PLUGIN_ID, space.gateway, PluginContext(run_id="fixed-run", config={})
        )
        assert outcome.proposal_id is not None
        detail = space.proposal_queries.get_proposal(ProposalId(UUID(outcome.proposal_id)))
        results.append(tuple(sorted(str(d["value"]) for d in detail.drafts)))

    assert results[0] == results[1]


def test_second_run_proposes_nothing_new_once_evidence_exists(tmp_path: Path) -> None:
    """Idempotent in effect: after the first proposal merges, a second run
    over the same content finds nothing left to propose."""
    space = build_plugin_space(tmp_path / "engram.db")
    _seed(space)
    space.rebuild()
    plugin = ReferenceUrlEvidencePlugin()
    space.registry.register(plugin)
    space.registry.enable(PLUGIN_ID)

    first = space.registry.run(PLUGIN_ID, space.gateway, PluginContext())
    proposal_id = ProposalId(UUID(str(first.proposal_id)))
    space.proposals.approve_proposal(proposal_id, None, HUMAN)
    space.proposals.merge_proposal(proposal_id, HUMAN)

    second = space.registry.run(PLUGIN_ID, space.gateway, PluginContext())
    assert second.ok is True
    assert second.candidate_count == 0
    assert second.proposal_id is None
