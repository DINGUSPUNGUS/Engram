"""Plugin provenance (ADR-0024 §7): explanatory only, folded by nothing.

Every read and every proposal a plugin causes carries a ``Provenance`` whose
``detail`` names exactly what produced it — mirroring
``AssistantGateway._provenance`` (ADR-0020 §4). Replay never parses this JSON;
it exists so a human reviewing a proposal (or the Observatory) can answer
"which plugin, which version, which capability, which run" without engram
having to remember any of that as event semantics.
"""

import json

from engram_events import Provenance
from engram_plugins.contract import Capability, PluginContext, PluginDescriptor

#: Every plugin actor is namespaced so it can never collide with a human
#: ("user"), an assistant ("chatgpt"), or "system" — and so recall-visibility
#: allow-lists can name a plugin explicitly if a memory ever restricts to one.
ACTOR_PREFIX = "plugin:"


def actor_for(descriptor: PluginDescriptor) -> str:
    return f"{ACTOR_PREFIX}{descriptor.plugin_id}"


def build_provenance(
    descriptor: PluginDescriptor,
    context: PluginContext,
    capability: Capability,
    *,
    provider: str | None = None,
    model: str | None = None,
) -> Provenance:
    """One provenance record for one plugin-caused read or proposal.

    ``provider``/``model`` are populated only when the plugin itself delegates
    to an ``LLMProvider`` (a plugin using ``intelligence_provider``-shaped
    logic internally) — ``None`` for a purely deterministic, rule-based plugin
    like the reference implementation.
    """
    return Provenance(
        actor=actor_for(descriptor),
        session_id=context.run_id,
        detail=json.dumps(
            {
                "plugin": {
                    "plugin_id": descriptor.plugin_id,
                    "plugin_version": descriptor.version,
                    "plugin_api_version": descriptor.api_version,
                    "capability": capability.value,
                    "config_identity": context.config_identity,
                    "source": context.source,
                    "run_id": context.run_id,
                    "provider": provider,
                    "model": model,
                }
            },
            sort_keys=True,
        ),
    )
