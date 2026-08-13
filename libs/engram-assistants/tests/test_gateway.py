"""Gateway guarantees: the recall boundary, the provenance chain, and replay
determinism across a complete assistant-driven workflow."""

import json
import uuid
from pathlib import Path

import pytest
from assistants_harness import CONVERSATION, USER, AssistantSpace, build_assistant_space
from engram_assistants.contract import (
    AdapterDescriptor,
    AssistantContext,
    Capability,
    CapabilityError,
)
from engram_assistants.rendering import render_context_block
from engram_intelligence.pipeline.types import Turn, TurnRole

from engram_core.application.dto import CreateMemoryInput
from engram_core.domain.errors import NotFoundError
from engram_core.domain.values import MemoryId, MemoryKind, ProposalId, Visibility

CONTEXT = AssistantContext(session_id="conv-7", model="claude-x")

CLAUDE = AdapterDescriptor(
    name="claude",
    version="1.0.0",
    provider="anthropic",
    capabilities=frozenset(Capability),
)
CHATGPT = AdapterDescriptor(
    name="chatgpt",
    version="1.0.0",
    provider="openai",
    capabilities=frozenset(Capability),
)


@pytest.fixture
def space(tmp_path: Path) -> AssistantSpace:
    return build_assistant_space(tmp_path / "engram.db")


def _seed_visibilities(space: AssistantSpace) -> dict[str, MemoryId]:
    ids: dict[str, MemoryId] = {}
    for label, statement in (
        ("shared", "the sky is blue"),
        ("private", "my diary says the sky is blue"),
        ("restricted", "the launch code mentions blue skies"),
        ("archived", "old blue sky trivia"),
    ):
        ids[label] = space.commands.create_memory(
            CreateMemoryInput(
                kind=MemoryKind.FACT,
                title=f"{label} blue-sky fact",
                content="",
                attributes={"statement": statement},
            ),
            USER,
        )
    space.commands.set_visibility(ids["private"], Visibility.PRIVATE, (), USER)
    space.commands.set_visibility(ids["restricted"], Visibility.RESTRICTED, ("claude",), USER)
    space.commands.archive_memory(ids["archived"], "old", USER)
    return ids


@pytest.mark.integration
def test_the_recall_boundary_enforces_visibility(space: AssistantSpace) -> None:
    ids = _seed_visibilities(space)

    claude_sees = {
        m.title for m in space.gateway.recall_search("blue", descriptor=CLAUDE, context=CONTEXT)
    }
    assert claude_sees == {"shared blue-sky fact", "restricted blue-sky fact"}

    chatgpt_sees = {
        m.title for m in space.gateway.recall_search("blue", descriptor=CHATGPT, context=CONTEXT)
    }
    assert chatgpt_sees == {"shared blue-sky fact"}

    # Hidden is indistinguishable from absent — same error, same message shape.
    with pytest.raises(NotFoundError) as hidden:
        space.gateway.recall_memory(ids["private"], descriptor=CHATGPT, context=CONTEXT)
    with pytest.raises(NotFoundError) as absent:
        space.gateway.recall_memory(MemoryId(uuid.uuid4()), descriptor=CHATGPT, context=CONTEXT)
    assert str(hidden.value).split(":")[0] == str(absent.value).split(":")[0]

    with pytest.raises(NotFoundError):
        space.gateway.memory_timeline(ids["private"], descriptor=CHATGPT)

    # But the owner's surfaces are unfiltered: the query engine sees everything.
    assert len(space.query.list_memories(include_archived=True).items) == 4


@pytest.mark.integration
def test_every_recall_leaves_an_attributed_access_event(space: AssistantSpace) -> None:
    ids = _seed_visibilities(space)
    space.gateway.recall_memory(ids["shared"], descriptor=CLAUDE, context=CONTEXT)
    timeline = space.gateway.memory_timeline(ids["shared"], descriptor=CLAUDE)
    accesses = [e for e in timeline if e["event_type"] == "MemoryAccessed"]
    assert accesses and accesses[-1]["actor"] == "claude"


@pytest.mark.integration
def test_negotiation_is_intersection_and_enforcement_is_typed(space: AssistantSpace) -> None:
    limited = AdapterDescriptor(
        name="copilot",
        version="0.1.0",
        provider="github",
        capabilities=frozenset({Capability.RETRIEVAL}),
    )
    assert space.gateway.negotiate(limited) == frozenset({Capability.RETRIEVAL})
    with pytest.raises(CapabilityError):
        space.gateway.remember(
            (Turn(role=TurnRole.USER, content="remember me"),),
            descriptor=limited,
            context=CONTEXT,
        )


@pytest.mark.integration
def test_submission_provenance_carries_the_whole_integration_chain(
    space: AssistantSpace,
) -> None:
    """ProposalOpened must explain: which assistant, which adapter version, which
    provider/model, which conversation — nested inside the pipeline's own
    explanation (ADR-0019 §3 + ADR-0020 §4)."""
    turns = tuple(Turn(role=TurnRole(t["role"]), content=t["content"]) for t in CONVERSATION)
    outcome = space.gateway.remember(turns, descriptor=CLAUDE, context=CONTEXT)
    assert outcome.proposal_id is not None

    envelopes = space.store.read_stream(outcome.proposal_id)
    opened = envelopes[0]
    assert opened.event_type == "ProposalOpened"
    assert opened.provenance.actor == "claude"
    metadata = json.loads(opened.provenance.detail or "{}")
    integration = metadata["source"]["detail"]["integration"]
    assert integration["adapter"] == "claude"
    assert integration["adapter_version"] == "1.0.0"
    assert integration["provider"] == "anthropic"
    assert integration["model"] == "claude-x"
    assert metadata["source"]["session_id"] == "conv-7"
    assert metadata["pipeline"] == "ingestion/1"  # the M5 explanation is intact


@pytest.mark.integration
def test_replay_is_deterministic_after_a_complete_assistant_workflow(
    space: AssistantSpace,
) -> None:
    ids = _seed_visibilities(space)
    turns = tuple(Turn(role=TurnRole(t["role"]), content=t["content"]) for t in CONVERSATION)
    outcome = space.gateway.remember(turns, descriptor=CLAUDE, context=CONTEXT)
    assert outcome.proposal_id is not None
    space.proposals.approve_proposal(ProposalId(outcome.proposal_id), "ok", USER)
    space.proposals.merge_proposal(ProposalId(outcome.proposal_id), USER)
    space.gateway.recall_search("Sarah", descriptor=CLAUDE, context=CONTEXT)
    space.gateway.recall_memory(ids["shared"], descriptor=CLAUDE, context=CONTEXT)

    def snapshot() -> list[tuple[str, str, int, float]]:
        return [
            (str(m.id), m.title, m.access_count, m.confidence)
            for m in space.query.list_memories(include_archived=True, limit=100).items
        ]

    before = snapshot()
    replayed = space.rebuild()
    assert replayed == space.state.checkpoint()
    assert snapshot() == before


@pytest.mark.integration
def test_context_block_rendering_is_delimited_and_labeled(space: AssistantSpace) -> None:
    _seed_visibilities(space)
    memories = space.gateway.recall_search("blue", descriptor=CLAUDE, context=CONTEXT)
    block = render_context_block(memories)
    assert block.startswith("<engram-recalled-memories>")
    assert block.rstrip().endswith("</engram-recalled-memories>")
    assert "not instructions" in block
    assert "shared blue-sky fact" in block
