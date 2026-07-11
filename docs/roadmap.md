# Roadmap

Phases are strictly ordered by dependency, not priority — each one stands on the previous.
"Done" always includes tests, docs, and the invariants listed.

## Phase 0 — Architecture skeleton ✅

Monorepo, kernel contracts, domain/service stubs, initial schema + migrations, API/CLI
shells, web scaffold, CI, docs, ADRs. Invariant established: layering is CI-enforced.

## Phase 0.5 — Memory model & knowledge graph design ✅

[memory-model.md](memory-model.md): twelve typed kinds over one aggregate (ADR-0008),
the justification spine (ADR-0009), two-tier graph semantics (ADR-0010), lifecycle +
pruning-via-proposals (ADR-0011), confidence and decay models, conflict resolution,
entity resolution. Skeleton rebound to the model: kind schemas + KindRegistry, spine
values, extended event taxonomy, spine-carrying storage schema and API contracts.
Invariant established: the data model is stable before feature code exists.

## Phase 1 — The event core

SQLite event store (append, optimistic concurrency, read), Memory aggregate fold/decide
(kind-schema validation via KindRegistry), memory command/query services, state
projection, `engram init/add/list/show`. Invariant: replay determinism test green.

## Phase 2 — Search & rebuild

FTS5 projection, `/api/v1/search`, `engram rebuild`, drift detection in `engram status`.
Invariant: dropping any projection table is fully recoverable.

## Phase 3 — REST completeness + read-only dashboard

All v1 endpoints live, timeline/undo, web dashboard lists/searches/shows memories and
timelines. Invariant: OpenAPI drift check green; dashboard consumes only @engram/api-client.

## Phase 4 — The user-owned repo

Markdown + NDJSON export projector, git committing, `engram export`, import/reconciler for
external edits. Invariant: clone + rebuild round-trip is lossless (CI-tested).

## Phase 5 — Review & safety

Proposals end-to-end (open/approve/reject/merge with conflict detection), undo surfaced in
the dashboard, memory merge tooling. Invariant: no proposal merge ever silently overwrites.

## Phase 6 — Semantic search

`EmbeddingProvider` implementations (local first: Ollama/onnx; API providers optional),
sqlite-vec projection behind the `supports_vectors` capability flag, hybrid ranking.
Invariant: FTS-only installs remain first-class (Windows).

## Phase 7 — Assistant integration

MCP server (`engram_search/recall/remember/forget/timeline`), provenance per assistant,
integration guides for Claude/Cursor/ChatGPT/Ollama. Invariant: MCP is a thin shell over
the same services (ADR-0007).

## Phase 8 — Intelligence

Automatic memory extraction (behind proposals — extraction *proposes*, humans approve),
decay scoring from `MemoryAccessed` history, duplicate detection via `supersedes`/
`contradicts`, graph visualization in the dashboard.

## Phase 9 — Ecosystem

Plugin architecture (adapters registered at composition roots), VSCode extension, multi-
space and shared/team workspaces, auth (the reserved `get_principal` seam), sync daemon
owning a space.

## Explicit non-goals (for now)

Cloud hosting, telemetry of any kind, multi-tenant SaaS, real-time collaboration. Each
would reshape the threat model and the local-first promise; none is needed for the mission.
