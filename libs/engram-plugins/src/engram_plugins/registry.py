"""PluginRegistry: discovery, registration, and lifecycle (ADR-0024 §§2, 6).

State here is entirely in-memory / process-local — a registry is rebuilt fresh
every process start from explicit ``register()`` calls or entry-point
discovery. Nothing about a plugin's registration status is ever recorded in the
event log: removing a plugin is deleting a dict entry, never appending an
event, which is exactly what "a plugin must be removable without corrupting or
invalidating existing memory history" requires (there is nothing in the log to
corrupt in the first place).
"""

import importlib.metadata
from collections.abc import Iterable
from dataclasses import dataclass
from enum import StrEnum

from engram_core.domain.errors import EngramError, NotFoundError
from engram_plugins.contract import (
    Capability,
    Plugin,
    PluginContext,
    PluginContractError,
    PluginDescriptor,
    PluginError,
    PluginRunResult,
)
from engram_plugins.gateway import PluginGateway

#: The standard entry-point group third-party packages publish plugins under
#: (``[project.entry-points."engram.plugins"]`` in their own pyproject.toml).
#: Discovery is a real, tested mechanism; no plugin marketplace or remote
#: registry is implied or built by it (ADR-0024 scope).
ENTRY_POINT_GROUP = "engram.plugins"


class PluginStatus(StrEnum):
    """Lifecycle states (ADR-0024 §2). ``REMOVED`` is not a stored state — a
    removed plugin has no record at all; it is returned from ``remove()`` for
    logging/demonstration purposes only."""

    REGISTERED = "registered"
    ENABLED = "enabled"
    DISABLED = "disabled"
    REMOVED = "removed"


@dataclass(frozen=True, slots=True)
class PluginRecord:
    descriptor: PluginDescriptor
    plugin: Plugin
    status: PluginStatus


class PluginRegistry:
    """Owns lifecycle; plugins themselves are stateless per run (ADR-0024)."""

    def __init__(self) -> None:
        self._records: dict[str, PluginRecord] = {}

    # -- registration & lifecycle --------------------------------------------------

    def register(self, plugin: Plugin) -> PluginDescriptor:
        """Register a plugin as ``REGISTERED`` (not yet runnable — call
        ``enable`` too). Re-registering the same ``plugin_id`` replaces the
        prior record (an upgrade or downgrade), always landing back in
        ``REGISTERED`` regardless of the prior status, so an operator must
        explicitly re-enable after any version change.

        Raises:
            PluginContractError: malformed descriptor (raised by
                ``PluginDescriptor.__post_init__`` itself) or a capability
                this engram build does not recognize.
        """
        descriptor = plugin.descriptor
        for capability in descriptor.capabilities:
            # Typed callers get this for free from the enum; this guards
            # descriptors built from untyped data (entry points, config
            # files) where a plain string could arrive instead of a real
            # Capability member.
            if not isinstance(capability, Capability):
                raise PluginContractError(
                    f"plugin {descriptor.plugin_id!r} declares unknown capability {capability!r}"
                )
        self._records[descriptor.plugin_id] = PluginRecord(
            descriptor, plugin, PluginStatus.REGISTERED
        )
        return descriptor

    def enable(self, plugin_id: str) -> None:
        record = self.get(plugin_id)
        self._records[plugin_id] = PluginRecord(
            record.descriptor, record.plugin, PluginStatus.ENABLED
        )

    def disable(self, plugin_id: str) -> None:
        """Blocks ``run()``; keeps the registration and history intact —
        distinct from ``remove`` (ADR-0024 non-negotiables: removability)."""
        record = self.get(plugin_id)
        self._records[plugin_id] = PluginRecord(
            record.descriptor, record.plugin, PluginStatus.DISABLED
        )

    def remove(self, plugin_id: str) -> PluginDescriptor:
        """Unregister entirely. Touches nothing in the event store — memory
        history that plugin ever produced remains exactly as merged.

        Raises:
            NotFoundError: unknown plugin_id.
        """
        record = self.get(plugin_id)
        del self._records[plugin_id]
        return record.descriptor

    def get(self, plugin_id: str) -> PluginRecord:
        record = self._records.get(plugin_id)
        if record is None:
            raise NotFoundError(f"no such plugin: {plugin_id}")
        return record

    def list(self, *, status: PluginStatus | None = None) -> tuple[PluginRecord, ...]:
        records: Iterable[PluginRecord] = self._records.values()
        if status is not None:
            records = (r for r in records if r.status is status)
        return tuple(sorted(records, key=lambda r: r.descriptor.plugin_id))

    # -- discovery -----------------------------------------------------------------

    def discover_entry_points(
        self, *, group: str = ENTRY_POINT_GROUP
    ) -> tuple[PluginDescriptor, ...]:
        """Find installed packages advertising plugins under ``group`` and
        register each as ``REGISTERED`` (discovery grants no trust — an
        operator must still ``enable`` each one explicitly).

        A plugin whose entry point fails to load or whose descriptor is
        malformed is skipped, not fatal to discovering the rest — one broken
        third-party package must not block every other plugin.
        """
        discovered: list[PluginDescriptor] = []
        for entry_point in importlib.metadata.entry_points(group=group):
            try:
                factory = entry_point.load()
                plugin = factory() if callable(factory) else factory
                discovered.append(self.register(plugin))
            except (EngramError, ImportError, TypeError, AttributeError):
                continue
        return tuple(discovered)

    # -- execution -------------------------------------------------------------------

    def run(
        self, plugin_id: str, gateway: PluginGateway, context: PluginContext
    ) -> PluginRunResult:
        """Run one enabled plugin. Any failure — an ``EngramError`` a gateway
        call raised, or an arbitrary exception the plugin's own code raised —
        is caught here and returned as a failed result, never propagated
        (ADR-0024 §6): one crashing plugin cannot take down the caller, and
        because ``submit_proposal`` is the only write and it happens only at
        the very end of a successful run, a crash leaves no partial state.

        Raises:
            NotFoundError: unknown plugin_id.
            PluginError: the plugin is not ENABLED.
        """
        record = self.get(plugin_id)
        if record.status is not PluginStatus.ENABLED:
            raise PluginError(
                f"plugin {plugin_id!r} is {record.status.value}; only enabled plugins run"
            )
        try:
            return record.plugin.run(context, gateway)
        except EngramError as exc:
            return PluginRunResult(
                ok=False,
                proposal_id=None,
                candidate_count=0,
                note=f"plugin {plugin_id!r} failed: {exc}",
                error=type(exc).__name__,
            )
        except Exception as exc:
            return PluginRunResult(
                ok=False,
                proposal_id=None,
                candidate_count=0,
                note=f"plugin {plugin_id!r} crashed",
                error=f"{type(exc).__name__}: {exc}",
            )


def register_all(registry: PluginRegistry, plugins: Iterable[Plugin]) -> None:
    """Convenience for composition roots registering several built-in plugins
    at once. Does not enable them — enabling is a separate, explicit decision."""
    for plugin in plugins:
        registry.register(plugin)
