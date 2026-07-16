# ADR-0020: One assistant gateway, many wire formats; the tool surface has no review verbs

- **Status**: Accepted
- **Date**: 2026-07-16

## Context

M6 connects ChatGPT, Claude, Gemini — and later Cursor, Copilot, local chat UIs — to
one memory substrate without weakening its guarantees. Three questions are not
covered by existing ADRs:

1. **Where does assistant integration live?** ADR-0007 forbids logic in interface
   shells, but the integration must drive the intelligence pipeline
   (`engram_intelligence`), which `engram_core` may not import — so the shared
   behavior can be in neither core nor an app.
2. **What may an assistant do, and how is that enforced?** Adapters written for
   vendor wire formats must not each re-decide policy, and a misbehaving adapter
   must not be *able* to bypass the proposal workflow.
3. **Where is recall visibility enforced?** memory-model.md §3 promises that
   `private` memories never reach assistants and `restricted` ones reach only
   allow-listed actors — a promise the CLI (a user surface) deliberately does not
   share.

## Decision

### 1. A new layer: `engram_assistants`, above the adapters, below the apps

```
apps        engram_api | engram_cli | engram_mcp
integration engram_assistants        ← the gateway + provider adapters
adapters    engram_storage_sqlite | engram_export_git | engram_intelligence
core        engram_core  (services, ports, recall policy)
kernel      engram_events
```

`engram_assistants` composes core services and the intelligence pipeline into one
provider-agnostic **AssistantGateway**. It is import-linter-enforced like every
other boundary, and it is as SDK-free as the core: provider adapters translate
*wire shapes* (JSON), they never import vendor SDKs.

The gateway's operations are deliberately few — exactly the assistant
responsibilities and nothing more:

| Operation | What it does | Capability required |
| --- | --- | --- |
| `recall_search` | query language over recallable memories; records `MemoryAccessed` per hit | `retrieval` |
| `recall_memory` | one memory by id; records access | `retrieval` |
| `remember` | conversation turns → intelligence pipeline → **one Proposal** | `proposal_submission` |
| `proposal_status` | review status of a proposal the assistant opened | `proposal_submission` |
| `memory_timeline` | a recallable memory's event history (explainability) | `timeline` |

**The tool surface contains no review verbs.** Approve, reject, merge, and undo
exist only on human surfaces (CLI today, dashboard in M7). Bypassing the proposal
workflow is not forbidden to adapters — it is *impossible* for them: the gateway
holds no reference to any event-appending service except the pipeline's proposal
door, and consent is structural: nothing an assistant submits becomes memory until
a human merges it.

### 2. Capabilities are declared by adapters and enforced by the gateway

Each adapter carries an immutable `AdapterDescriptor` (name, adapter version,
provider, declared capabilities). Negotiation is intersection: the gateway grants
`declared ∩ supported` and every operation checks its required capability against
the *descriptor the adapter presented*, raising a typed `CapabilityError` that each
adapter maps to its provider's error shape (`is_error` tool results, never a
crash). Degradation is graceful by construction: an adapter lacking
`tool_calling` can still receive recalled memories as a delimited plain-text
context block.

Canonical tool semantics (names, JSON-schema parameters, argument validation,
dispatch) are defined **once**, next to the gateway. A provider adapter contributes
only three translations: definitions → provider schema shape, provider tool-call →
(name, args), result/error → provider result shape. Identical behavior across
providers is therefore not a testing goal but a construction property — and the
shared contract test suite verifies it anyway.

### 3. Recall visibility is a core policy, applied at the gateway

The rule (`private` never; `restricted` only to allow-listed actors; a hidden
memory is indistinguishable from an absent one) is a pure function in
`engram_core.application.recall` — core owns the policy. The gateway is the recall
boundary that applies it; the CLI remains a user surface and shows everything.
Recalled content is rendered inside clearly delimited data blocks (security.md:
memories are data, not instructions).

### 4. Observability rides the mechanisms that already exist

Every recall appends `MemoryAccessed` with the assistant's actor identity (the
retention signal and the access audit are the same event). Every submission's
`Provenance.detail` carries the integration metadata — adapter name and version,
provider, model, conversation/session id, capabilities used — alongside the M5
pipeline metadata (ADR-0019 §3). Explanatory only; folded by nothing.

## Consequences

- New assistants are one small adapter file; behavior cannot drift because it
  lives once, in the gateway. ✔
- No adapter, however buggy, can append an event or approve its own proposal. ✔
- The MCP server (transport for Claude-family clients) becomes a thin stdio shell
  over the same gateway when the transport lands; it inherits every guarantee. ✔
- Cost: one more package and layer row to maintain; assistants that legitimately
  need richer verbs (e.g. bulk export) must wait for a gateway operation.

## Alternatives considered

- **Gateway as core application service with a submission port**: keeps it in
  core but forces the pipeline's Transcript types into core or a duplicate DTO —
  a worse wall than a new layer. Rejected.
- **Per-adapter service calls (no gateway)**: three adapters × policy = drift and
  bypass risk; the review rule "logic in a tool-handler is a bug" (ADR-0007)
  would be violated three times over. Rejected.
- **Review verbs behind an "auto-approve" capability**: ADR-0011 reserves approval
  policy for the human/owner; an assistant-side capability would relitigate that
  decision by the back door. Rejected.
