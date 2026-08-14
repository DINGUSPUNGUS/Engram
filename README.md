# engram

> **Status: pre-1.0.** The event core works (M1), the query engine works (M2), the
> space is portable (M3), every mutation flows through a **review pipeline** (M4), and
> the **intelligence pipeline is live** (M5): `engram ingest` extracts typed, evidence-
> cited memory candidates from conversations — locally, via Ollama — and its only power
> is to open a proposal. AI proposes; events decide. **Assistants are connected** (M6):
> ChatGPT, Claude, and Gemini share the substrate through one gateway whose tool surface
> has no review verbs. **The web dashboard is live** (M7): Memory Explorer, Proposal
> Review, Timeline, Observatory, Console, and Settings, with SSE live updates. **The
> plugin architecture is live** (M8): a capability-gated, read-plus-one-proposal-door
> extension surface, proven by a reference plugin wired into the CLI. M9 (hardening,
> packaging, upgrade story, docs, performance) is in progress. The MCP transport itself
> remains a stub over the existing assistant gateway ([roadmap](docs/roadmap.md)).

**engram** is a local-first, user-owned memory engine for AI assistants. It lets ChatGPT,
Claude, Gemini, Cursor, Copilot, Ollama, and anything else that speaks MCP or REST share a
single persistent memory that *you* own — as an event log you can replay, a SQLite database
you can query, and a git repository of markdown files you can read, grep, and take anywhere.

Two principles govern everything here:

1. **AI proposes; events decide.** No model is ever authoritative — automation can only
   open proposals; only approved events change memory (ADR-0011/0012).
2. **Boringly trustworthy.** Not flashy, not magical: every action is explainable,
   reproducible, versioned, and reversible. If you ever wonder "why did it do that?",
   the system can answer (ADR-0015).

## How it stores memory

Three storage concerns, three canonical layers ([ADR-0001](docs/adr/0001-three-layer-storage.md)):

```
Conversations / Assistants / CLI / Web
              │  commands
              ▼
        Memory Engine (application services)
              │  appends
              ▼
   EVENT LOG — append-only, system of record (SQLite)
              │  projected into
   ┌──────────┼──────────────────┐
   ▼          ▼                  ▼
SQLite      Search index       Markdown export
state       (FTS / vectors,    (.md + frontmatter)
tables      later)                   │
(canonical runtime state)            ▼
                              Git repository
                              (canonical history, portable, user-owned)
```

- **SQLite is the canonical runtime state.** Search, graph traversal, decay, dedup, and
  analytics are database problems, so state lives in a database.
- **Markdown is the canonical portable representation.** Every memory is exported as a
  human-readable file with YAML frontmatter.
- **Git is the canonical history.** Exports are committed; the event log is also exported as
  NDJSON, so `git clone` + `engram rebuild` losslessly reconstitutes the database anywhere.
- **Event-sourced from day 1** ([ADR-0002](docs/adr/0002-event-sourcing.md)): state changes
  are immutable events (`MemoryCreated`, `MemoryEdited`, …). Undo, audit, timelines, and
  replay come from the architecture, not from features.

## Monorepo layout

| Path | What it is |
| --- | --- |
| `libs/engram-events` | Kernel: event envelope, registry, bus/store/projection contracts. Zero dependencies. |
| `libs/engram-core` | Domain aggregates, value objects, ports; application command/query services. |
| `libs/engram-storage-sqlite` | Canonical store: SQLModel event store + state projections + Alembic migrations. |
| `libs/engram-export-git` | Markdown/NDJSON export projector, git committer, inbound reconciler. |
| `libs/engram-intelligence` | AI layer: ingestion pipeline contracts, LLM provider port (SDKs confined to `providers/`), versioned prompts, eval harness. |
| `libs/engram-assistants` | Assistant integration layer: the provider-agnostic gateway + ChatGPT/Claude/Gemini adapters (wire-format translation only, ADR-0020). |
| `libs/engram-plugins` | Plugin architecture: capability-gated `PluginGateway` + `PluginRegistry` for third-party extensions (read + propose only, ADR-0024). |
| `libs/engram-observatory` | Explainability: the audit graph answering "why did it do that?" (decision traces, not logs). |
| `evaluations/` | Golden cases + synthetic corpus spec + the committed quality baseline. |
| `apps/api` | FastAPI REST server (thin shell over application services). |
| `apps/cli` | `engram` command-line interface (Typer). |
| `apps/mcp` | MCP server (stub — the assistant gateway it will wrap is done; the stdio transport itself isn't built yet). |
| `apps/web` | Next.js 15 dashboard: Memory Explorer, Proposal Review, Timeline, Observatory, Console, Settings (M7). |
| `packages/api-client` | TypeScript client generated from the OpenAPI contract. |
| `docs/` | Architecture, ADRs, conventions, roadmap. Start with [docs/architecture.md](docs/architecture.md). |

## Quickstart

Prerequisites: [Node 22+](https://nodejs.org), [pnpm 9+](https://pnpm.io),
[uv](https://docs.astral.sh/uv/) (uv installs Python 3.13 for you).

```sh
pnpm install                 # JS workspace
uv sync --all-packages       # Python workspace (fetches Python 3.13 if needed)

uv run engram init           # create your memory space (~/.engram)
uv run engram add fact "I prefer dark mode" -t ui
uv run engram add project myapp --attr name=myapp --attr status=active
uv run engram list
uv run engram search "kind:project status:active dark mode"   # the query language
uv run engram show <id>      # full state + event timeline
uv run engram show <id> --version 1   # time travel: the memory as it first existed
uv run engram status         # event log totals + projection drift detection (checkpoint lag)
uv run engram status --verify  # + differential rebuild: catches wrong *content* at lag 0 too
uv run engram rebuild        # drop projections, replay the log — same state

uv run engram export         # deterministic markdown+NDJSON repo (~/.engram/memory)
uv run engram git init       # version it; `engram git commit` = export + commit
uv run engram import ./notes.md          # validated → opens a PROPOSAL, never a write
uv run engram import --restore <repo>    # rebuild an empty space losslessly

uv run engram ingest ./conversation.txt  # the AI pipeline (Ollama, local): extract →
                                         # resolve → score → ONE proposal, never a write
uv run engram confirm <id>               # vouch: confidence rises (policy-weighted)
uv run engram contradict <id> --by <id>  # dispute: confidence decays + contradicts edge
uv run engram importance <id> --pin -w 0.9   # importance signals (scores stay derived)

uv run engram proposals list             # the review queue
uv run engram proposals show <id>        # inspect every draft intent
uv run engram proposals approve <id> && uv run engram proposals merge <id>
uv run engram proposals undo <id>        # compensating events — history never rewritten

pnpm dev                     # API on :8000, web dashboard on :3000
```

Everything runs locally. No Docker required (compose files exist for convenience), no cloud,
no accounts, no telemetry.

## Documentation

- [Architecture](docs/architecture.md) — the full picture, including a self-critique
- [The Memory Model](docs/memory-model.md) — twelve typed kinds + the justification spine
- [The Export Format](docs/export-format.md) — the portable repository: markdown, NDJSON, manifest, restore vs import
- [Intelligence](docs/intelligence.md) — ingestion pipeline, provider port, prompts, evals
- [Assistant Integrations](docs/integrations.md) — the gateway, adapters, capabilities, the recall boundary
- [Domain model](docs/domain-model.md) · [Events](docs/events.md) · [Data flow](docs/data-flow.md)
- [REST API](docs/api.md) · [Conventions](docs/conventions.md) · [Operations](docs/operations.md)
- [Security](docs/security.md) · [Roadmap](docs/roadmap.md) · [ADRs](docs/adr/)

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md). The one rule you cannot break: **imports point
inward** (`apps → adapters → core → events`) — CI enforces it with import-linter.

## License

[Apache-2.0](LICENSE)
