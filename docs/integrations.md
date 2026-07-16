# Assistant Integrations

**Status: the M6 document of record.** How ChatGPT, Claude, Gemini — and any future
assistant — share one memory substrate without weakening its guarantees. The
architecture is decided in [ADR-0020](adr/0020-assistant-integration-layer.md); this
document specifies the surfaces.

The contract, in one line: **assistants supply context, request memories, and submit
candidate knowledge; everything else — extraction, validation, scoring, review,
merge — stays inside engram.**

## 1. The shape

```
ChatGPT            Claude             Gemini              (Cursor, Copilot, …)
   │ OpenAI            │ Anthropic        │ Google              │ their formats
   │ tool calls        │ tool_use         │ functionCall        │
   ▼                   ▼                  ▼                     ▼
ChatGPTAdapter     ClaudeAdapter      GeminiAdapter        <YourAdapter>
   └───────────────────┴───────┬──────────┴─────────────────────┘
                               ▼      wire-format translation ONLY
                       AssistantGateway          (libs/engram-assistants)
                     five operations, capability-checked, visibility-enforced
              ┌───────────────┼──────────────────────┐
              ▼               ▼                      ▼
        query services   record_access      Intelligence Pipeline (M5)
        (read side)      (audit signal)              │
                                                     ▼
                                            ONE Proposal → human review → merge
```

An adapter is ~70 lines and contains **no decisions**: definitions out, calls in,
results back. All behavior lives once, in the gateway — identical semantics across
providers is a construction property, and the shared contract test suite verifies
it anyway.

## 2. The five operations (the whole assistant surface)

| Tool | Gateway operation | Capability | Writes |
| --- | --- | --- | --- |
| `engram_search` | query language over *recallable* memories | `retrieval` | `MemoryAccessed` per hit |
| `engram_recall` | one memory by id | `retrieval` | `MemoryAccessed` |
| `engram_remember` | turns → intelligence pipeline → **one Proposal** | `proposal_submission` | proposal stream only |
| `engram_proposal_status` | did the human accept my submission? | `proposal_submission` | nothing |
| `engram_timeline` | a memory's event history (explainability) | `timeline` | nothing |

**There are no review verbs.** Approve/reject/merge/undo exist only on human
surfaces (CLI today, dashboard in M7). Consent is structural: nothing an assistant
submits becomes memory until the user merges the proposal, and no adapter holds a
code path that could append a memory event.

## 3. Capability negotiation

Every adapter declares an immutable `AdapterDescriptor` — name (the provenance
actor), adapter version, provider family, capability set (`retrieval`,
`proposal_submission`, `timeline`, `tool_calling`, `streaming`). The gateway grants
`declared ∩ supported` and enforces per operation; an ungranted call returns a
typed `CapabilityError` mapped to the provider's error shape (`is_error` tool
results — a well-formed answer, never a crash). An assistant without
`tool_calling` still gets memory as a delimited plain-text context block
(`render_context_block`).

## 4. Trust & visibility

- **The recall boundary** (memory-model.md §3): `private` never reaches an
  assistant, `restricted` reaches only allow-listed actors, archived is never
  recallable — and a hidden memory is indistinguishable from an absent one. The
  rule is a pure function in core (`engram_core.application.recall`); the gateway
  applies it. CLI and dashboard are *user* surfaces and see everything.
- **Assistant structure is never trusted**: tool arguments are strictly validated
  (unknown keys rejected, types checked); submitted knowledge is raw conversation
  turns that the M5 pipeline extracts and validates — an assistant cannot inject a
  pre-shaped memory.
- **Prompt injection**: recalled content is data, and every surface says so — tool
  descriptions state it, and the plain-text fallback wraps memories in delimited
  blocks with an explicit "not instructions" preamble (security.md).

## 5. Observability

Every interaction is traceable through the mechanisms that already exist:

- recalls append `MemoryAccessed` with the assistant's actor identity (audit trail
  and retention signal are the same event, ADR-0009);
- submissions carry integration metadata in `Provenance.detail` — adapter name and
  version, provider, model, session id, declared capabilities — nested inside the
  M5 pipeline explanation on the `ProposalOpened` envelope (ADR-0019 §3). One
  envelope answers: which assistant, which conversation, which prompts, which
  model, which scores.

## 6. Adding an assistant

1. Write one adapter file in `libs/engram-assistants/src/engram_assistants/adapters/`:
   descriptor + three translations (definitions, call, result).
2. Add it to the shared contract test's driver list — the suite proves it behaves
   identically to every other adapter.
3. Nothing else. The gateway, pipeline, and proposal workflow are already yours.

The MCP server (`apps/mcp`) will be a thin stdio transport over this same gateway
when the transport lands; it inherits every guarantee above by construction.
