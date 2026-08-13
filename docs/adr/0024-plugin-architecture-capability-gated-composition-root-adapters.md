# ADR-0024: Plugins are capability-gated adapters at the composition root, in-process, never in the replay path

- **Status**: Accepted
- **Date**: 2026-08-13

## Context

M8 asks whether engram's architecture can become an extensible platform without
weakening its trust model. Two things already constrain the answer before any new
design work:

1. **architecture.md §4** already names the seam: *"a plugin is an adapter
   registered at the composition root."* Every external dependency — storage,
   export, LLM provider — already crosses into engram-core through a `Protocol`
   in `engram_core.domain.ports` (or, for the LLM boundary, `engram_intelligence.
   provider.LLMProvider`), named only in each app's `runtime.py`. There is no
   reserved-but-unbuilt "plugin port" waiting to be filled in; the pattern itself
   *is* the plugin mechanism, and M8's job is to generalize and formalize it for
   third-party code rather than invent a new one.
2. **ADR-0020** (M6) already solved an almost identical problem one layer up:
   how does external code (assistants) touch memory without becoming a trusted
   authority? Its answer — one gateway, capability negotiation as
   `declared ∩ supported`, no review verbs on the tool surface, provenance
   riding `Provenance.detail` — is the direct precedent for plugins. Plugins are
   a superset of the assistant problem (they may also *provide* implementations
   of ports, not just *consume* memory), so the design below extends ADR-0020's
   shape rather than replacing it. **`engram_assistants` is not touched by this
   ADR** — it is a stable, already-shipped instance of the same idea; unifying
   it with the new general plugin layer is explicitly deferred (see
   Alternatives).

Three things must be decided that no existing ADR covers: the capability
vocabulary and how it forbids a generic "do anything" grant, the plugin
lifecycle/registration/versioning model, and — the one genuinely new question —
the isolation/security stance for code that, unlike the three built-in assistant
adapters, was not written by the engram maintainers.

## Decision

### 1. A new layer, `engram_plugins`, a peer of `engram_assistants`

```
apps        engram_api | engram_cli | engram_mcp
integration engram_assistants | engram_plugins   ← peers; neither depends on the other
adapters    engram_storage_sqlite | engram_export_git | engram_intelligence
core        engram_core  (services, ports, recall policy)
kernel      engram_events
```

Import-linter enforces this like every other boundary. `engram_plugins` depends
on `engram_core` and `engram_events` only — never on `engram_storage_sqlite`,
`engram_export_git`, or any app package. This is the first, structural answer to
"what prevents accidental Event Store access": the package that plugin code runs
inside is architecturally incapable of importing the store.

### 2. Two shapes of plugin, one descriptor/lifecycle model

Inspecting the codebase surfaces that "plugin" already means two different
things here, and conflating them would be the "generic capability" mistake in
disguise:

- **Consumer plugins** call *into* engram through a gateway, like an assistant
  does. They request candidate knowledge from the engine and, at most, submit a
  proposal. Capabilities: `memory_read`, `query`, `timeline_read`,
  `evidence_read`, `proposal_submit`.
- **Provider plugins** are called *by* engram — they implement an existing core
  port (`LLMProvider`, `MarkdownSync`/`VersionControl`) or the existing
  `AssistantAdapter` protocol. Capabilities: `intelligence_provider`,
  `export_provider`, `assistant_adapter`.

Both shapes share one `PluginDescriptor` (id, version, plugin-contract
`api_version`, declared capabilities) and one `PluginRegistry` lifecycle
(`registered → enabled → disabled`, plus `removed`). They differ in *how* a
capability is exercised at runtime:

- Consumer capabilities are negotiated and enforced by a new **`PluginGateway`**
  (this ADR, `SUPPORTED = {memory_read, query, timeline_read, evidence_read,
  proposal_submit}`) — the exact `declared ∩ supported` mechanics as
  `AssistantGateway`.
- Provider capabilities have **no gateway operation at all**. Declaring
  `intelligence_provider` is metadata — it means "this plugin object also
  satisfies the `LLMProvider` Protocol" — and a human wires it in at a
  composition root exactly as `apps/cli/ingestion.py` already wires in
  `OllamaProvider` today. `PluginGateway.negotiate()` therefore never grants a
  provider-tier capability; attempting to *run* one through the gateway is
  the same `CapabilityError` as any undeclared capability, which is the
  intended, tested "capability denial" behavior for this milestone — provider
  capabilities are declared for discovery and documentation now; wiring one in
  is a manual composition-root decision, not an automatic grant.

This directly satisfies "no generic can-do-anything capability": there is no
capability whose enforcement is "anything goes," and the two mechanisms
(gateway-enforced vs. port-implemented) are visibly different in the code, not
just by convention.

### 3. Capability tiers make the trust boundary visible in the type system

```python
class CapabilityTier(StrEnum):
    READ = "read"
    PROPOSAL = "proposal"
    PROVIDER = "provider"
    MUTATION = "mutation"   # reserved; no capability is ever assigned this tier
```

`MUTATION` exists and is permanently empty. This is deliberate, not an
oversight: per the non-negotiables, no plugin capability may write a memory
event directly, so the tier that *would* hold such a capability has nothing in
it, and a reviewer (or a test) can assert `tier_of(c) is not MUTATION` for
every capability that exists. `proposal_submit` is tiered `PROPOSAL`, not
`MUTATION`, because opening a proposal appends an event only to the *Proposal*
aggregate's own stream (`ProposalOpened`) — never to a Memory stream, and it
changes no memory truth. This is the same door `ProposalCommandService.
open_proposal` already gives the M3 importer and the M4 reconciler; `M8` adds
one more caller class to a door that has existed since M4, it does not cut a
new one.

### 4. Approval and merge are structurally unreachable from a plugin

`PluginGateway` has no `approve`, `reject`, `merge`, or `undo` method — the same
absence-by-construction `AssistantGateway` uses. A plugin holding
`proposal_submit` receives back a `ProposalId` and nothing else; the only
services capable of approving or merging (`ProposalCommandService.
approve_proposal` / `merge_proposal`) are never given to plugin code, at the
type level. This is verified by a test that asserts `PluginGateway` exposes no
such attribute, plus an integration test that merging a plugin's own just-opened
proposal fails with `ConflictError` (not approved) exactly like any other
unapproved proposal.

### 5. Isolation: architectural, not adversarial — stated explicitly

**Plugins execute in-process, as ordinary Python.** `engram_plugins` does not
implement, and this ADR does not authorize, any process boundary, sandbox, or
capability-restricted runtime (no `subprocess`, no WASM, no seccomp). The
isolation this milestone provides is:

- **Structural**: a plugin object receives only a `PluginGateway` and a
  `PluginContext` — never a repository, the event store, or the bus. There is
  no reference for well-behaved plugin code to reach further.
- **Declarative/enforced-at-the-boundary**: the gateway checks every operation
  against `declared ∩ supported`; an undeclared or unsupported capability
  raises `CapabilityError` before any port method runs.
- **Compile-time/CI**: import-linter forbids `engram_plugins` from importing the
  storage or export packages at all.

**What this does not do**: stop a plugin that is willing to `import
engram_storage_sqlite` (or `os`, or `sqlite3`) directly in its own module from
doing so — Python has no in-process capability system, and pretending otherwise
would be dishonest. Today's trust model (security.md) already treats everything
running as the local user as one trust domain with no auth boundary; a plugin
the user installed is exactly as trusted as an `LLMProvider` implementation the
user configured, which is already true of `OllamaProvider` today. **If hostile
(not-fully-trusted) plugin code must be contained, that is a new trust boundary
this project does not have anywhere yet, and it needs its own ADR plus a real
sandbox/runtime design — not a decision to smuggle into M8.** This ADR
explicitly declines to build one; see Alternatives.

### 6. Failure containment

Every `run()` call is wrapped by the registry in a broad exception boundary —
deliberately broader than the `EngramError`-only boundary `engram_assistants`
uses, because plugin code (unlike the three in-tree adapters) was not written
under this project's discipline and may raise anything:

```python
try:
    return plugin.run(context, gateway)
except EngramError as exc:
    return PluginRunResult(ok=False, ..., error=type(exc).__name__)
except Exception as exc:  # noqa: BLE001 — untrusted plugin code
    return PluginRunResult(ok=False, ..., error=f"{type(exc).__name__}: {exc}")
```

A crashing plugin returns a failed `PluginRunResult`; it cannot take down the
caller, and — because no write happened before the crash (the only write is one
atomic `open_proposal` call at the very end of a successful `run()`) — it leaves
no partial state.

### 7. Provenance, not event coupling

Every proposal a plugin opens carries a `Provenance` whose `detail` is a JSON
blob (mirroring `AssistantGateway._provenance`, ADR-0020 §4) recording: plugin
id, plugin version, plugin `api_version`, the capability used, a
`config_identity` (a hash of the plugin's run configuration — never the raw
config, and never a field the aggregate branches on), a run id, and
provider/model if the plugin itself delegates to an `LLMProvider`. This is
**explanatory only, folded by nothing** — replay never parses `Provenance.
detail`. Mutable plugin configuration therefore never enters event semantics; it
can change freely between runs without touching how any past event replays.

### 8. Versioning: two numbers, one opaque, one enforced

- `descriptor.version` (the plugin's own semver) is opaque provenance, exactly
  like `LLMResponse.model_id` — never branched on by engram.
- `PLUGIN_API_VERSION` (currently `1`) is the plugin *contract's* own version.
  `PluginRegistry.register()` rejects a descriptor declaring an unsupported
  `api_version`. This is the same two-tier versioning `draft_schema_version`
  already uses for proposal drafts (ADR-0018) — a second instance of an
  existing pattern, not a new one.

### 9. Replay never executes plugin code

Nothing above changes what replay already is: `Memory.fold` /
`rebuild_projections` read `EventEnvelope.payload` through the event registry
and `KindRegistry` only. They have never imported, called, or even known about
`engram_plugins`. A plugin-opened proposal, once merged, produced ordinary
Memory events indistinguishable at replay time from ones a human typed via
`engram add`. Removing the plugin, upgrading it, downgrading it, or leaving it
crashing forever changes nothing about whether those events replay — proven by
a dedicated test (`test_replay_without_plugin.py`) that rebuilds projections
from a real event log with `engram_plugins.plugins.reference_url_evidence`
never imported into the test process at all.

## Consequences

- A third-party consumer plugin is one small `Plugin` implementation (descriptor
  + `run(context, gateway)`), exactly as an assistant adapter is one small file. ✔
- No plugin, however buggy or malicious in intent, can append a memory event,
  approve, or merge — the gateway holds no reference capable of it. ✔
- Provider-tier capabilities (`intelligence_provider`, `export_provider`,
  `assistant_adapter`) are declared and discoverable now, without wiring a
  gateway operation that doesn't exist yet — they compose exactly like
  `OllamaProvider` already does. ✔
- The isolation story is honestly weaker than "sandboxed": a plugin author who
  imports internals directly bypasses everything above. This is stated, not
  hidden, and matches the project's existing single-trust-domain security
  model. If that ever needs to change, it is a new ADR and likely a new runtime
  topology (subprocess/RPC), not a patch to this one.
- One more package to maintain; `engram_assistants` and `engram_plugins`
  temporarily overlap in *shape* (both are capability-gated gateways) without
  sharing code, which is accepted for this milestone (see Alternatives).

## Alternatives considered

- **Fold plugins into `engram_assistants`, generalizing `AssistantAdapter` into
  `Plugin`**: would unify the two gateways, but rewrites a stable, ADR-0020-
  governed, already-shipped layer to serve a request M8 did not make ("do not
  redesign the core because the dashboard/a new milestone exposes an
  inconvenient edge case"). Rejected for M8; recorded here as the natural
  future consolidation once both layers have shipped plugins to compare.
- **One generic `Capability.ALL` / "trusted plugin" flag**: explicitly forbidden
  by the milestone brief and by ADR-0020's own precedent (no
  auto-approve-style capability was allowed there either, ADR-0020
  Alternatives). Rejected.
- **Out-of-process plugins (subprocess, RPC, WASM sandbox)**: the only design
  that would give real hostile-code isolation. Rejected *for this milestone*
  because nothing in the current architecture demands it yet (no external
  plugin has shipped) and because the brief is explicit: stop and write an ADR
  before building a sandbox/runtime. That ADR does not yet have a forcing
  function; when one appears (e.g., a plugin marketplace with untrusted
  authors), this decision should be revisited first, before any runtime code.
- **Let plugins call `ProposalCommandService` directly instead of through a
  gateway**: removes capability negotiation and the single provenance-shaping
  choke point; a plugin without `proposal_submit` declared would have no
  structural block. Rejected for the same reason ADR-0020 rejected
  per-adapter service calls: policy would live in N places instead of one.
- **Give plugins their own `MemoryRepository`/`EventStore` reference "for
  performance"**: directly contradicts the non-negotiables. Rejected outright.
