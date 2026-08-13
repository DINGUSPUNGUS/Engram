"""PluginRegistry: lifecycle, discovery, validation, failure isolation
(ADR-0024 §§2, 6). No database needed — the registry is pure bookkeeping."""

from dataclasses import dataclass
from typing import TYPE_CHECKING, cast

import pytest

from engram_core.domain.errors import NotFoundError, ValidationError
from engram_plugins.contract import (
    Capability,
    PluginContext,
    PluginContractError,
    PluginDescriptor,
    PluginError,
    PluginRunResult,
)
from engram_plugins.registry import PluginRegistry, PluginStatus, register_all

if TYPE_CHECKING:
    from engram_plugins.gateway import PluginGateway

#: These tests exercise registry bookkeeping only — none of the stub plugins
#: below touch the gateway, so a real one (five wired services) is unneeded.
_NO_GATEWAY = cast("PluginGateway", object())


@dataclass(frozen=True, slots=True)
class _StubPlugin:
    plugin_id: str = "dev.engram.stub"
    fail_with: Exception | None = None

    @property
    def descriptor(self) -> PluginDescriptor:
        return PluginDescriptor(
            plugin_id=self.plugin_id,
            name="Stub",
            version="1.0.0",
            api_version=1,
            capabilities=frozenset({Capability.PROPOSAL_SUBMIT}),
        )

    def run(self, context: PluginContext, gateway: object) -> PluginRunResult:
        if self.fail_with is not None:
            raise self.fail_with
        return PluginRunResult(ok=True, proposal_id=None, candidate_count=0, note="ran fine")


@dataclass(frozen=True, slots=True)
class _BadCapabilityPlugin:
    """A descriptor whose capabilities set was built from untyped data (e.g. a
    config file or entry point) rather than the ``Capability`` enum."""

    @property
    def descriptor(self) -> PluginDescriptor:
        return PluginDescriptor(
            plugin_id="dev.engram.bad-capability",
            name="Bad",
            version="1.0.0",
            api_version=1,
            capabilities=frozenset({"totally-made-up"}),  # type: ignore[arg-type]
        )

    def run(self, context: PluginContext, gateway: object) -> PluginRunResult:
        raise AssertionError("must never run: registration should have rejected it")


def test_register_lands_in_registered_not_runnable() -> None:
    registry = PluginRegistry()
    registry.register(_StubPlugin())
    record = registry.get("dev.engram.stub")
    assert record.status is PluginStatus.REGISTERED
    with pytest.raises(PluginError):
        registry.run("dev.engram.stub", gateway=_NO_GATEWAY, context=PluginContext())


def test_enable_then_run_succeeds() -> None:
    registry = PluginRegistry()
    registry.register(_StubPlugin())
    registry.enable("dev.engram.stub")
    result = registry.run("dev.engram.stub", gateway=_NO_GATEWAY, context=PluginContext())
    assert result.ok is True


def test_disable_blocks_run_but_keeps_registration() -> None:
    registry = PluginRegistry()
    registry.register(_StubPlugin())
    registry.enable("dev.engram.stub")
    registry.disable("dev.engram.stub")
    assert registry.get("dev.engram.stub").status is PluginStatus.DISABLED
    with pytest.raises(PluginError):
        registry.run("dev.engram.stub", gateway=_NO_GATEWAY, context=PluginContext())


def test_remove_deletes_the_registration_entirely() -> None:
    registry = PluginRegistry()
    registry.register(_StubPlugin())
    removed = registry.remove("dev.engram.stub")
    assert removed.plugin_id == "dev.engram.stub"
    with pytest.raises(NotFoundError):
        registry.get("dev.engram.stub")
    assert registry.list() == ()


def test_register_rejects_a_descriptor_with_an_unknown_capability() -> None:
    registry = PluginRegistry()
    with pytest.raises(PluginContractError):
        registry.register(_BadCapabilityPlugin())
    assert registry.list() == ()


def test_run_isolates_an_arbitrary_exception() -> None:
    """A crashing plugin must never propagate past the registry — it is
    untrusted input, not a trusted call (ADR-0024 §6)."""
    registry = PluginRegistry()
    plugin = _StubPlugin(fail_with=RuntimeError("boom"))
    registry.register(plugin)
    registry.enable(plugin.plugin_id)
    result = registry.run(plugin.plugin_id, gateway=_NO_GATEWAY, context=PluginContext())
    assert result.ok is False
    assert result.error is not None and "RuntimeError" in result.error


def test_run_isolates_an_engram_error() -> None:
    registry = PluginRegistry()
    plugin = _StubPlugin(fail_with=ValidationError("bad drafts"))
    registry.register(plugin)
    registry.enable(plugin.plugin_id)
    result = registry.run(plugin.plugin_id, gateway=_NO_GATEWAY, context=PluginContext())
    assert result.ok is False
    assert result.error == "ValidationError"


def test_list_filters_by_status() -> None:
    registry = PluginRegistry()
    register_all(
        registry, [_StubPlugin(plugin_id="dev.engram.a"), _StubPlugin(plugin_id="dev.engram.b")]
    )
    registry.enable("dev.engram.a")
    assert {r.descriptor.plugin_id for r in registry.list(status=PluginStatus.ENABLED)} == {
        "dev.engram.a"
    }
    assert {r.descriptor.plugin_id for r in registry.list(status=PluginStatus.REGISTERED)} == {
        "dev.engram.b"
    }
    assert len(registry.list()) == 2


def test_reregistering_resets_to_registered_even_if_previously_enabled() -> None:
    """An upgrade or downgrade always requires an explicit re-enable — a
    version change is never silently trusted (ADR-0024 §8)."""
    registry = PluginRegistry()
    registry.register(_StubPlugin())
    registry.enable("dev.engram.stub")
    registry.register(_StubPlugin())  # simulate re-registering (e.g. an upgrade)
    assert registry.get("dev.engram.stub").status is PluginStatus.REGISTERED


def test_discover_entry_points_registers_each_and_skips_broken_ones(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import importlib.metadata as metadata

    class _GoodEntryPoint:
        name = "good"

        def load(self) -> type[_StubPlugin]:
            return _StubPlugin

    class _BrokenEntryPoint:
        name = "broken"

        def load(self) -> object:
            raise ImportError("dependency missing")

    def fake_entry_points(*, group: str) -> tuple[object, ...]:
        assert group == "engram.plugins"
        return (_GoodEntryPoint(), _BrokenEntryPoint())

    monkeypatch.setattr(metadata, "entry_points", fake_entry_points)
    registry = PluginRegistry()
    discovered = registry.discover_entry_points()
    assert [d.plugin_id for d in discovered] == ["dev.engram.stub"]
    assert registry.get("dev.engram.stub").status is PluginStatus.REGISTERED
