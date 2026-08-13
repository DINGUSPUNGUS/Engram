"""The plugin contract (ADR-0024): what every plugin must declare, and the
capability vocabulary that draws the line between reading, proposing, and
providing.

Deliberately narrow. A plugin is *not* a trusted authority: it is untrusted
input to the same Proposal → Review → Merge pipeline every other automated
source (the M5 intelligence pipeline, an assistant's ``remember``) already goes
through. Nothing here grants a plugin the ability to append a memory event,
approve anything, or merge anything — those verbs simply do not exist on the
surfaces a plugin receives.
"""

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from typing import TYPE_CHECKING, Protocol
from uuid import uuid4

from engram_core.domain.errors import EngramError

if TYPE_CHECKING:
    # Only for the type checker: engram_plugins.gateway imports this module,
    # so a real (runtime) import here would be circular. The forward
    # reference below is exact for structural Protocol matching without one.
    from engram_plugins.gateway import PluginGateway

#: The plugin contract's own schema version (distinct from a plugin's own
#: semver — mirrors ``draft_schema_version``, ADR-0018). Bumped only when the
#: shape of ``Plugin``/``PluginDescriptor`` itself changes.
PLUGIN_API_VERSION = 1
SUPPORTED_API_VERSIONS: frozenset[int] = frozenset({PLUGIN_API_VERSION})


class CapabilityTier(StrEnum):
    """What kind of thing a capability lets a plugin do (ADR-0024 §3).

    ``MUTATION`` is declared and permanently empty: no capability is ever
    assigned this tier. It exists so "no plugin capability performs a direct
    mutation" is a checkable fact (``tier_of(c) is not MUTATION`` for every
    ``c``), not just a claim in a docstring.
    """

    READ = "read"
    PROPOSAL = "proposal"
    PROVIDER = "provider"
    MUTATION = "mutation"  # reserved; nothing is ever tiered here


class Capability(StrEnum):
    """Explicit, enumerated plugin capabilities. There is no "do anything"
    member — every capability here is one specific, narrow thing."""

    # -- read tier: consumer plugins, enforced by PluginGateway ------------------
    MEMORY_READ = "memory_read"
    QUERY = "query"
    TIMELINE_READ = "timeline_read"
    EVIDENCE_READ = "evidence_read"

    # -- proposal tier: consumer plugins, enforced by PluginGateway --------------
    PROPOSAL_SUBMIT = "proposal_submit"

    # -- provider tier: the plugin implements an existing core port; no gateway
    #    operation exists for these (ADR-0024 §2) — declaring one is metadata,
    #    wiring one in is a manual composition-root decision.
    INTELLIGENCE_PROVIDER = "intelligence_provider"
    EXPORT_PROVIDER = "export_provider"
    ASSISTANT_ADAPTER = "assistant_adapter"


_TIERS: dict[Capability, CapabilityTier] = {
    Capability.MEMORY_READ: CapabilityTier.READ,
    Capability.QUERY: CapabilityTier.READ,
    Capability.TIMELINE_READ: CapabilityTier.READ,
    Capability.EVIDENCE_READ: CapabilityTier.READ,
    Capability.PROPOSAL_SUBMIT: CapabilityTier.PROPOSAL,
    Capability.INTELLIGENCE_PROVIDER: CapabilityTier.PROVIDER,
    Capability.EXPORT_PROVIDER: CapabilityTier.PROVIDER,
    Capability.ASSISTANT_ADAPTER: CapabilityTier.PROVIDER,
}


def tier_of(capability: Capability) -> CapabilityTier:
    """Every capability's tier. Total over the enum — new capabilities must be
    tiered here or this raises, which is the point."""
    return _TIERS[capability]


class PluginError(EngramError):
    """Base class for plugin-layer errors. Never raised across a gateway
    operation without being caught by the registry (ADR-0024 §6)."""


class CapabilityError(PluginError):
    """The operation needs a capability the plugin did not declare, or one
    engram does not grant through the gateway (undeclared or provider-tier)."""


class PluginContractError(PluginError):
    """A descriptor or plugin object violates the contract itself: bad id
    shape, unsupported ``api_version``, or an unknown capability name."""


_ID_PATTERN_MSG = (
    "plugin_id must be lowercase, dot/hyphen-separated, e.g. 'dev.engram.reference-tagger'"
)


@dataclass(frozen=True, slots=True)
class PluginDescriptor:
    """A plugin's immutable self-description; stamped into every trace it
    produces. Never mutated after registration — an upgrade registers a new
    descriptor under the same ``plugin_id`` (ADR-0024 §8)."""

    plugin_id: str  # namespaced identity, e.g. "dev.engram.reference-tagger"
    name: str  # human-readable display name
    version: str  # the plugin's own semver string; opaque provenance only
    api_version: int  # which PLUGIN_API_VERSION this descriptor targets
    capabilities: frozenset[Capability]
    description: str = ""

    def __post_init__(self) -> None:
        if not self.plugin_id or not all(
            ch.islower() or ch.isdigit() or ch in ".-" for ch in self.plugin_id
        ):
            raise PluginContractError(f"{self.plugin_id!r}: {_ID_PATTERN_MSG}")
        if not self.version:
            raise PluginContractError(f"plugin {self.plugin_id!r} declares an empty version")
        if self.api_version not in SUPPORTED_API_VERSIONS:
            raise PluginContractError(
                f"plugin {self.plugin_id!r} targets api_version={self.api_version},"
                f" but this engram only supports {sorted(SUPPORTED_API_VERSIONS)}"
            )

    @property
    def qualified_name(self) -> str:
        return f"{self.plugin_id}@{self.version}"


@dataclass(frozen=True, slots=True)
class PluginContext:
    """Per-run identity and configuration. Plugins are stateless between runs —
    everything run-scoped arrives here.

    ``config`` is never written into event semantics (ADR-0024 §7): only its
    ``config_identity`` (a hash) rides provenance. Two runs with the same
    ``config`` produce the same identity; the raw values never reach the log.
    """

    run_id: str = field(default_factory=lambda: str(uuid4()))
    source: str = "manual"  # what triggered this run, e.g. "cli:plugins run"
    config: Mapping[str, object] = field(default_factory=dict)

    @property
    def config_identity(self) -> str:
        """A short, deterministic fingerprint of ``config``. Pure function of
        its contents — order-independent, never the raw values themselves."""
        canonical = json.dumps(self.config, sort_keys=True, default=str)
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]


@dataclass(frozen=True, slots=True)
class PluginRunResult:
    """What one ``Plugin.run()`` produced. ``ok=False`` on any failure — a
    crash never propagates past the registry (ADR-0024 §6)."""

    ok: bool
    proposal_id: str | None
    candidate_count: int
    note: str
    error: str | None = None


class Plugin(Protocol):
    """What every plugin offers. One entry point: read what its declared
    capabilities allow through the gateway, decide on candidate knowledge,
    optionally submit ONE proposal. Never receives a repository, the event
    store, or the bus — only a capability-gated ``PluginGateway``."""

    @property
    def descriptor(self) -> PluginDescriptor: ...

    def run(self, context: "PluginContext", gateway: "PluginGateway") -> PluginRunResult:
        """Execute one run.

        Raises:
            Nothing a well-behaved plugin needs to catch — the registry
            isolates any exception (ADR-0024 §6). Plugins written against this
            contract should still prefer returning ``ok=False`` over raising,
            but raising is safe.
        """
        ...
