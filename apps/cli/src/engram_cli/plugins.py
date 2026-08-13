"""Plugin composition for the CLI (ADR-0024): the only place `engram plugins`
names a concrete plugin implementation. Mirrors ``ingestion.py``'s role for
the intelligence pipeline — everything else (the registry, the gateway, the
capability model) lives in ``engram_plugins`` and is untouched here.
"""

from engram_cli.runtime import Runtime
from engram_plugins.gateway import PluginGateway
from engram_plugins.plugins.reference_url_evidence import ReferenceUrlEvidencePlugin
from engram_plugins.registry import PluginRegistry


def build_plugin_registry() -> PluginRegistry:
    """The in-tree reference plugin, registered and enabled by default.

    A real deployment would also call ``registry.discover_entry_points()``
    here to pick up installed third-party packages — omitted for the CLI's
    default composition since none exist yet; the mechanism is already
    library-level and tested (``engram_plugins.registry``)."""
    registry = PluginRegistry()
    registry.register(ReferenceUrlEvidencePlugin())
    registry.enable(ReferenceUrlEvidencePlugin().descriptor.plugin_id)
    return registry


def build_plugin_gateway(runtime: Runtime) -> PluginGateway:
    return PluginGateway(
        queries=runtime.queries,
        search=runtime.search,
        timeline=runtime.timeline,
        commands=runtime.commands,
        proposals=runtime.proposals,
    )
