# engram

> **Status: pre-alpha.** The event core works (M1) and so does the query engine (M2):
> `engram init / add / list / show / search / status / rebuild` store and query real,
> typed, replayable memories — including time travel (`show --at`). The markdown/git
> export, proposals, the AI pipeline, and the surfaces land milestone by milestone
> ([roadmap](docs/roadmap.md)).

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
| `libs/engram-observatory` | Explainability: the audit graph answering "why did it do that?" (decision traces, not logs). |
| `evaluations/` | Golden cases + synthetic corpus spec + the committed quality baseline. |
| `apps/api` | FastAPI REST server (thin shell over application services). |
| `apps/cli` | `engram` command-line interface (Typer). |
| `apps/mcp` | MCP server (stub — milestone M6). |
| `apps/web` | Next.js 15 dashboard. |
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
uv run engram status         # event log totals + projection drift detection
uv run engram rebuild        # drop projections, replay the log — same state

pnpm dev                     # API on :8000, web on :3000 (route stubs until M7)
```

Everything runs locally. No Docker required (compose files exist for convenience), no cloud,
no accounts, no telemetry.

## Documentation

- [Architecture](docs/architecture.md) — the full picture, including a self-critique
- [The Memory Model](docs/memory-model.md) — twelve typed kinds + the justification spine
- [Intelligence](docs/intelligence.md) — ingestion pipeline, provider port, prompts, evals
- [Domain model](docs/domain-model.md) · [Events](docs/events.md) · [Data flow](docs/data-flow.md)
- [REST API](docs/api.md) · [Conventions](docs/conventions.md) · [Operations](docs/operations.md)
- [Security](docs/security.md) · [Roadmap](docs/roadmap.md) · [ADRs](docs/adr/)

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md). The one rule you cannot break: **imports point
inward** (`apps → adapters → core → events`) — CI enforces it with import-linter.

## License

[Apache-2.0](LICENSE)
