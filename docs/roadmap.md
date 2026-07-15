# Roadmap

Milestones are strictly ordered by dependency, not priority — each one stands on the
previous. "Done" always includes tests, docs, and the invariants listed. The architecture
is frozen (2026-07-12); the milestones are about the *product*.

> **History note.** Early work was tracked as "phases" (0, 0.5, 0.75, 1); those all fold
> into M1 below. ADRs and commit messages written before the rename still say "phase".

## M1 — Event Store ✅

Everything from the architecture skeleton through the working event core:

- Monorepo, kernel contracts (`engram-events`), CI-enforced hexagonal layering,
  API/CLI/web shells, ADRs 0001–0007 (formerly phase 0).
- [memory-model.md](memory-model.md): twelve typed kinds over one aggregate (ADR-0008),
  the justification spine (ADR-0009), two-tier graph (ADR-0010), pruning-via-proposals
  (ADR-0011) (formerly phase 0.5).
- [intelligence.md](intelligence.md): the nine-stage ingestion pipeline, the
  `LLMProvider` port with vendor SDKs confined to adapters (ADR-0012), prompts as code
  (ADR-0013), the evaluation gate (ADR-0014), and the observatory reservation (ADR-0015)
  (formerly phases 0.75 + freeze).
- The working core: SQLite event store (append, optimistic concurrency, typed payload
  codec), Memory aggregate fold/evolve/decide for the narrative core, command/query
  services, the checkpointed state projection, `engram init/add/list/show/rebuild`
  (formerly phase 1).

**Invariant green**: the replay-determinism test drives the full write path, resets,
replays, and asserts identical state. Never let that test disappear.

## M2 — Query Engine

Not a search feature: a query *language* over the projections, in which full-text match
is just one operator (ADR-0016). `engram search "kind:project status:active tag:oss
confidence>0.8 dark mode"` — typed operators (`kind:`, `tag:`, `slug:`, `visibility:`,
`is:archived|pinned|stale`, `confidence>`, `updated:`/`created:`, `has:evidence|links`,
`linked:`, kind-attribute `key:value` fallthrough) plus free text against an FTS5
projection. Also: `engram status` with projection drift detection, and **time travel** —
`engram show <id> --at <timestamp> | --version N` reconstructs a memory exactly as it
was (a developer's debugging tool that falls straight out of ADR-0002).
Invariant: dropping any projection table is fully recoverable (`engram rebuild`).

## M3 — Git Export & Interoperability ✅

Not "export markdown": prove the event store can produce a completely portable,
human-editable repository with deterministic reconstruction (ADR-0017,
[export-format.md](export-format.md)). Deterministic `engram export`
(markdown + NDJSON + checksummed manifest with a Merkle-style root; repeated exports
touch nothing), `engram import` (exhaustive validation → **proposals**, never direct
writes) and `engram import --restore` (verbatim event-log reconstitution into an empty
space), `engram git init|status|commit` (git consumes exports, never mutates runtime
state), plus links + evidence command paths (portability demanded they exist in the
log). **Invariant green**: export → delete database → restore → rebuild reproduces
identical events and identical state, and re-exports to an identical merkle root.

## M4 — Proposal Workflow ✅

Every mutation flows through a trustworthy review pipeline (ADR-0018). Drafts are
**intents**, not events; merge re-drives them through the aggregate against current
state and is the only event producer — one atomic batch per merge. Conflict
detection compares stream history (`base_version` vs head), never projections.
Undo compensates (inverse events in reverse order + `ProposalUndone`) and refuses
if anything moved since the merge. The **reconciler**: importing a document whose
id exists folds the current aggregate, computes the semantic diff, and proposes
edit intents — never a duplicate `MemoryCreated`; unchanged imports open nothing.
Plus: proposals projection + `engram proposals list/show/approve/reject/merge/undo`,
attribute/visibility/lifetime commands, `MemoryEvidenceRetracted`.
**Invariant green**: no merge without approval, no approval bypass, atomic merges,
and replay determinism holds across the full import→merge→undo lifecycle.
Deferred within the spine: confirm/contradict/importance (they are scoring-policy
judgments — they land with M5's scoring work).

## M5 — Intelligence Pipeline

Implements M1's frozen contracts ([intelligence.md](intelligence.md)): Ollama provider
first (local-first reference), then evidence extraction → entity resolution → candidate
generation → conflict detection, each gated by the golden suite (ADR-0014). Decay
scoring from `MemoryAccessed` history, the synthetic-corpus generator, duplicate
detection. Semantic search lands here too — `EmbeddingProvider` implementations and a
sqlite-vec projection joining the query engine as new operators behind the
`supports_vectors` capability flag. Invariants: no AI-affecting change merges below
baseline; FTS-only installs remain first-class (Windows).

## M6 — Assistant Integrations

MCP server (`engram_search/recall/remember/forget/timeline`), provenance per assistant,
integration guides for Claude/Cursor/ChatGPT/Ollama. Invariant: MCP is a thin shell over
the same services (ADR-0007).

## M7 — Web Dashboard

REST completeness (all v1 endpoints live, timeline/undo over HTTP) and the dashboard:
list/query/show memories, timelines, proposal review UI, graph visualization.
Invariant: OpenAPI drift check green; dashboard consumes only `@engram/api-client`.

## M8 — Plugins & Ecosystem

Plugin architecture (adapters registered at composition roots), VSCode extension,
multi-space and shared/team workspaces, auth (the reserved `get_principal` seam),
sync daemon owning a space.

## M9 — 1.0

Hardening, packaging (pipx/homebrew/winget), docs site, upgrade/migration story,
performance pass (snapshotting if replay cost ever demands it — ADR-0002 reserves it).

## Explicit non-goals (for now)

Cloud hosting, telemetry of any kind, multi-tenant SaaS, real-time collaboration. Each
would reshape the threat model and the local-first promise; none is needed for the mission.
