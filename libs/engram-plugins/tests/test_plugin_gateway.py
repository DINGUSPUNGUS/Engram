"""PluginGateway: capability negotiation/denial, visibility, and the fact that
approval/merge are structurally unreachable (ADR-0024 §§2, 4)."""

from pathlib import Path

import pytest
from plugins_harness import build_plugin_space

from engram_core.domain.errors import ConflictError, NotFoundError
from engram_core.domain.values import MemoryKind, Visibility
from engram_plugins.contract import Capability, CapabilityError, PluginContext, PluginDescriptor
from engram_plugins.gateway import PluginGateway


def _descriptor(*capabilities: Capability, plugin_id: str = "dev.engram.test") -> PluginDescriptor:
    return PluginDescriptor(
        plugin_id=plugin_id,
        name="Test",
        version="1.0.0",
        api_version=1,
        capabilities=frozenset(capabilities),
    )


def test_gateway_has_no_review_verbs() -> None:
    """No matter what capabilities exist, the class itself cannot approve or
    merge — the review verbs simply are not methods (ADR-0024 §4)."""
    for verb in ("approve_proposal", "reject_proposal", "merge_proposal", "undo_proposal"):
        assert not hasattr(PluginGateway, verb)


def test_ungranted_capability_is_denied(tmp_path: Path) -> None:
    space = build_plugin_space(tmp_path / "engram.db")
    descriptor = _descriptor()  # no capabilities declared at all
    with pytest.raises(CapabilityError):
        space.gateway.query("http", descriptor=descriptor, context=PluginContext())


def test_provider_tier_capability_is_never_granted(tmp_path: Path) -> None:
    """Declaring a provider-tier capability gets a plugin nothing from the
    gateway — there is no operation for it (ADR-0024 §2)."""
    space = build_plugin_space(tmp_path / "engram.db")
    descriptor = _descriptor(Capability.INTELLIGENCE_PROVIDER)
    assert space.gateway.negotiate(descriptor) == frozenset()
    with pytest.raises(CapabilityError):
        space.gateway.query("http", descriptor=descriptor, context=PluginContext())


def test_negotiation_is_declared_intersect_supported(tmp_path: Path) -> None:
    space = build_plugin_space(tmp_path / "engram.db")
    descriptor = _descriptor(Capability.QUERY, Capability.INTELLIGENCE_PROVIDER)
    assert space.gateway.negotiate(descriptor) == frozenset({Capability.QUERY})


def test_private_memory_is_hidden_from_a_plugin_exactly_like_an_assistant(tmp_path: Path) -> None:
    space = build_plugin_space(tmp_path / "engram.db")
    memory_id = space.add_memory(
        MemoryKind.FACT,
        "Secret",
        "See http://example.com/secret",
        visibility=Visibility.PRIVATE,
        statement="secret",
    )
    space.rebuild()
    descriptor = _descriptor(Capability.MEMORY_READ)
    with pytest.raises(NotFoundError):
        space.gateway.get_memory(memory_id, descriptor=descriptor, context=PluginContext())


def test_query_records_memory_accessed(tmp_path: Path) -> None:
    from engram_core.application.queries.timeline_queries import TimelineQueryService

    space = build_plugin_space(tmp_path / "engram.db")
    memory_id = space.add_memory(
        MemoryKind.FACT, "Doc", "See http://example.com/doc", statement="doc"
    )
    space.rebuild()
    descriptor = _descriptor(Capability.QUERY)
    hits = space.gateway.query("http", descriptor=descriptor, context=PluginContext())
    assert any(h.id == str(memory_id) for h in hits)

    timeline = TimelineQueryService(space.query).memory_timeline(memory_id)
    accessed = [e for e in timeline if e.event_type == "MemoryAccessed"]
    assert len(accessed) == 1
    assert accessed[0].actor == "plugin:dev.engram.test"


def test_submit_proposal_opens_pending_never_merged(tmp_path: Path) -> None:
    from uuid import UUID

    from engram_core.application.commands.drafts import AddEvidenceDraft
    from engram_core.domain.values import ProposalId
    from engram_events import Provenance

    space = build_plugin_space(tmp_path / "engram.db")
    memory_id = space.add_memory(
        MemoryKind.FACT, "Doc", "See http://example.com/doc", statement="doc"
    )
    descriptor = _descriptor(Capability.PROPOSAL_SUBMIT)

    proposal_id = space.gateway.submit_proposal(
        "Add evidence",
        "found a url",
        [
            AddEvidenceDraft(
                memory_id=memory_id,
                base_version=0,
                evidence_type="uri",
                value="http://example.com/doc",
            )
        ],
        descriptor=descriptor,
        context=PluginContext(),
    )
    detail = space.proposal_queries.get_proposal(ProposalId(UUID(proposal_id)))
    assert detail.status == "pending"

    # The proposal cannot be merged without a human approval step first — a
    # plugin's own submission can never fast-track itself (ADR-0018 §2).
    with pytest.raises(ConflictError):
        space.proposals.merge_proposal(ProposalId(UUID(proposal_id)), Provenance(actor="user"))
