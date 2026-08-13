# Plugins

**Status: the M8 document of record.** How third-party code extends engram
without becoming a trusted authority. The architecture is decided in
[ADR-0024](adr/0024-plugin-architecture-capability-gated-composition-root-adapters.md);
this document specifies the surfaces.

The contract, in one line: **a plugin reads what its declared capabilities
allow and, at most, opens one proposal; everything else — validation, review,
merge, replay — stays inside engram and never executes plugin code.**

## 1. The shape

```
Third-party plugin code
   │ implements Plugin: descriptor + run(context, gateway)
   ▼
PluginRegistry            (engram_plugins) — lifecycle only, no trust granted
   │ registered → enabled → run()
   ▼
PluginGateway              capability-gated: declared ∩ supported
   ├─ memory_read / query / timeline_read / evidence_read  → existing read services
   └─ proposal_submit                                       → ProposalCommandService.open_proposal
                                                                     │
                                                              ONE Proposal → human review → merge
```

A consumer plugin is one small object: a `PluginDescriptor` and a `run()`
method. It never receives a repository, the event store, or the bus — only
the gateway, which is exactly as capability-gated as `AssistantGateway`
(ADR-0020) and shares its shape deliberately.

## 2. The capability model (the whole plugin surface)

| Capability | Tier | What it does | Enforced by |
| --- | --- | --- | --- |
| `memory_read` | read | one memory by id, recall-filtered | `PluginGateway.get_memory` |
| `query` | read | query-language search (ADR-0016), recall-filtered | `PluginGateway.query` |
| `timeline_read` | read | a memory's event history | `PluginGateway.timeline_for` |
| `evidence_read` | read | a memory's current evidence list | `PluginGateway.evidence_for` |
| `proposal_submit` | proposal | open ONE proposal | `PluginGateway.submit_proposal` |
| `intelligence_provider` | provider | the plugin implements `LLMProvider` | a composition root, manually |
| `export_provider` | provider | the plugin implements `MarkdownSync`/`VersionControl` | a composition root, manually |
| `assistant_adapter` | provider | the plugin implements `AssistantAdapter` | a composition root, manually |

**There is no mutation-tier capability, ever** — `CapabilityTier.MUTATION`
exists in the code and is permanently empty. `proposal_submit` looks like a
write but isn't one against memory: it appends only to the Proposal
aggregate's own stream (`ProposalOpened`), never to a Memory stream, and
changes no memory truth by itself.

**Provider-tier capabilities have no gateway operation.** Declaring
`intelligence_provider` is metadata (discovery/documentation); actually using
one means the plugin object also satisfies `engram_intelligence.provider.
LLMProvider`, wired in at a composition root exactly like `OllamaProvider`
already is — the same mechanism that has existed since ADR-0012, not a new
one.

## 3. Lifecycle

```
register() → REGISTERED  (not runnable)
enable()   → ENABLED     (runnable)
disable()  → DISABLED    (blocked; registration and history intact)
remove()   → gone entirely (no event, nothing in the log to corrupt)
```

Re-registering the same `plugin_id` (an upgrade or downgrade) always lands
back in `REGISTERED` — an operator must explicitly re-enable after any
version change; nothing is silently trusted across a version bump.

## 4. Discovery

`PluginRegistry.discover_entry_points()` finds packages advertising plugins
under the `engram.plugins` entry-point group and registers each — discovery
grants no trust; an operator still enables explicitly. A broken third-party
package is skipped, not fatal to the rest. The CLI's default composition
(`engram_cli.plugins`) registers only the in-tree reference plugin; entry-point
discovery is available and tested at the library level for real installs.

## 5. Provenance

Every plugin-caused read or proposal carries a `Provenance` whose `detail` is
a JSON blob naming: plugin id, plugin version, the plugin contract's own
`api_version`, the capability used, a `config_identity` (a hash — never the
raw configuration), a run id, and provider/model if the plugin itself
delegates to an LLM. This mirrors `AssistantGateway._provenance` (ADR-0020
§4) exactly and is **explanatory only, folded by nothing**.

One nuance worth stating plainly: a **merged memory event carries the human
reviewer's provenance**, not the plugin's — `ProposalCommandService.
merge_proposal` stamps every resulting event with whoever called merge
(ADR-0018). The plugin's own provenance lives on the proposal's own
`ProposalOpened` event, which is where the M5 pipeline's explanation already
lives (ADR-0019 §3) and is where the dashboard's Observatory should look to
answer "which plugin proposed this."

## 6. Isolation and security — stated exactly, not softened

Plugins run **in-process**. This is architectural isolation (capability
gating, a narrow object surface, import-linter boundaries), not a security
sandbox — a plugin willing to import internals directly can still do so;
Python has no in-process capability system. Today's engram trust model
(security.md) already treats everything running as the local user as one
trust domain; a plugin the user installed is exactly as trusted as an
`LLMProvider` implementation they configured. If hostile-plugin isolation is
ever required, that is a new trust boundary needing its own ADR and a real
sandbox/runtime — not something this milestone builds or pretends to have
built. See ADR-0024 §5 for the full reasoning.

Every `run()` is wrapped in a broad exception boundary (broader than
`engram_assistants` uses, because plugin code is less trusted than the
in-tree adapters): any exception, not just `EngramError`, becomes a failed
`PluginRunResult` rather than propagating. An undeclared or unsupported
capability raises `CapabilityError` before any port method runs.

## 7. Replay never executes plugin code

`Memory.fold` / `rebuild_projections` read `EventEnvelope.payload` through the
event registry and `KindRegistry` only — they have never imported or called
`engram_plugins`. Removing a plugin, upgrading it, downgrading it, or leaving
it permanently crashing changes nothing about whether its historical events
replay. `libs/engram-plugins/tests/test_replay_without_plugin.py` proves this
directly: it rebuilds projections from a real event log with the reference
plugin's module removed from `sys.modules`, and asserts it never reappears
there across the rebuild.

## 8. Adding a plugin

1. Implement `Plugin` (descriptor + `run(context, gateway)`) in your own
   package. Declare only the capabilities you use.
2. Either register it explicitly at a composition root, or publish an
   `engram.plugins` entry point for `discover_entry_points()` to find.
3. Nothing else. The registry, gateway, capability model, and Proposal →
   Review → Merge pipeline are already yours — and cannot be bypassed, because
   your plugin object never receives anything capable of bypassing them.
