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
    """The in-tree reference plugin, registered and enabled by default, plus
    whatever third-party packages the active environment has installed under
    the ``engram.plugins`` entry-point group (docs/plugins.md §4/§8).

    Discovery grants no trust: a discovered plugin lands at ``REGISTERED``,
    not ``ENABLED`` (ADR-0024 §3) — an operator must still explicitly
    ``engram plugins enable <id>`` before it can run. This was previously a
    tested-but-uncalled library mechanism (M9 packaging audit): a package
    installed alongside engram and correctly advertising the entry point
    was never actually discovered by the real CLI binary, only by
    ``engram_plugins.registry``'s own unit tests calling it directly."""
    registry = PluginRegistry()
    registry.register(ReferenceUrlEvidencePlugin())
    registry.enable(ReferenceUrlEvidencePlugin().descriptor.plugin_id)
    registry.discover_entry_points()
    return registry


def build_plugin_gateway(runtime: Runtime) -> PluginGateway:
    return PluginGateway(
        queries=runtime.queries,
        search=runtime.search,
        timeline=runtime.timeline,
        commands=runtime.commands,
        proposals=runtime.proposals,
    )
