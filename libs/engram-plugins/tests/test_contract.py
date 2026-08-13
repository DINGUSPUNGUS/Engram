"""The plugin contract itself: descriptor validation, capability tiers,
versioning (ADR-0024 §§3, 8)."""

import pytest

from engram_plugins.contract import (
    Capability,
    CapabilityTier,
    PluginContext,
    PluginContractError,
    PluginDescriptor,
    tier_of,
)


def _descriptor(**overrides: object) -> PluginDescriptor:
    fields: dict[str, object] = {
        "plugin_id": "dev.engram.example",
        "name": "Example",
        "version": "1.0.0",
        "api_version": 1,
        "capabilities": frozenset({Capability.QUERY}),
    }
    fields.update(overrides)
    return PluginDescriptor(**fields)  # type: ignore[arg-type]


def test_descriptor_rejects_bad_id() -> None:
    with pytest.raises(PluginContractError):
        _descriptor(plugin_id="Not A Valid Id!")


def test_descriptor_rejects_empty_version() -> None:
    with pytest.raises(PluginContractError):
        _descriptor(version="")


def test_descriptor_rejects_unsupported_api_version() -> None:
    with pytest.raises(PluginContractError):
        _descriptor(api_version=999)


def test_qualified_name() -> None:
    assert _descriptor().qualified_name == "dev.engram.example@1.0.0"


def test_every_capability_is_tiered() -> None:
    for capability in Capability:
        assert tier_of(capability) in CapabilityTier


def test_mutation_tier_is_permanently_empty() -> None:
    """No plugin capability may ever be a direct mutation (ADR-0024 §3,
    non-negotiable: plugins must never append events directly)."""
    assert all(tier_of(c) is not CapabilityTier.MUTATION for c in Capability)


def test_read_and_proposal_tiers_are_distinct_from_provider_tier() -> None:
    read = {c for c in Capability if tier_of(c) is CapabilityTier.READ}
    proposal = {c for c in Capability if tier_of(c) is CapabilityTier.PROPOSAL}
    provider = {c for c in Capability if tier_of(c) is CapabilityTier.PROVIDER}
    assert read == {
        Capability.MEMORY_READ,
        Capability.QUERY,
        Capability.TIMELINE_READ,
        Capability.EVIDENCE_READ,
    }
    assert proposal == {Capability.PROPOSAL_SUBMIT}
    assert provider == {
        Capability.INTELLIGENCE_PROVIDER,
        Capability.EXPORT_PROVIDER,
        Capability.ASSISTANT_ADAPTER,
    }
    assert read.isdisjoint(proposal)
    assert read.isdisjoint(provider)
    assert proposal.isdisjoint(provider)


def test_config_identity_is_deterministic() -> None:
    a = PluginContext(run_id="r1", config={"query": "http", "limit": 5})
    b = PluginContext(run_id="r2", config={"limit": 5, "query": "http"})  # different key order
    assert a.config_identity == b.config_identity


def test_config_identity_changes_with_config() -> None:
    a = PluginContext(config={"query": "http"})
    b = PluginContext(config={"query": "www"})
    assert a.config_identity != b.config_identity
