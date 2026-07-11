# Contributing to engram

Thanks for your interest! This document covers setup, the architectural rules that keep the
codebase healthy, and the mechanics of landing a change.

## Setup

```sh
git clone <your-fork>
cd engram
pnpm install   # JS side
uv sync        # Python side (installs Python 3.13 + all workspace packages)
pnpm dev       # run API (:8000) + web (:3000)
```

Useful commands (run from the repo root):

| Command | What it does |
| --- | --- |
| `pnpm lint` | Ruff + Biome across all packages (via turbo) |
| `pnpm run lint:architecture` | import-linter layering contracts |
| `pnpm typecheck` | mypy (strict) + tsc |
| `pnpm test` | pytest + vitest |
| `pnpm gen:client` | regenerate the TS API client from the OpenAPI schema |

## The architecture rules (non-negotiable)

1. **Imports point inward only.** `apps → adapters (storage/export) → engram-core →
   engram-events`. `engram-core` never imports an adapter; `engram-events` imports nothing
   from this repo. CI runs `lint-imports` and will fail your PR otherwise.
2. **State changes are events.** There is no `UPDATE memories` anywhere. Commands go through
   an aggregate, which emits events; projections fold events into query state. If you need a
   new kind of change, add an event type — see below.
3. **Identity is the UUID.** Never address a memory by slug or filename; both are mutable
   projections of events.
4. **Reads are ordinary calls.** Query services read projection tables synchronously. Don't
   route reads through the event bus.
5. **Interface layers are thin.** A router/CLI command/MCP tool parses input, calls one
   application service, maps the result. Logic in a router is a bug.

## How to add an event type

1. Define the payload dataclass in `libs/engram-core/src/engram_core/domain/events.py`
   with `schema_version = 1` and register it in the event registry.
2. Teach the owning aggregate to emit it (`decide`) and fold it (`evolve`).
3. Update every projection that cares (state tables, exporter).
4. Add a unit test: *given* events, *when* command, *then* new events.
5. Never change a shipped payload shape in place — bump `schema_version` and add an
   upcaster. Old logs must replay forever.

## How to add or evolve a memory kind

Kinds are versioned schemas, not aggregates (ADR-0008, docs/memory-model.md):

1. Add/extend the frozen attributes dataclass in
   `libs/engram-core/src/engram_core/domain/kinds.py`. Closed vocabularies are
   `StrEnum`s.
2. Never change a shipped shape in place — bump the kind's `schema_version` in
   `build_kind_registry()` and register an upcaster.
3. Add the kind's half-life and staleness threshold to `domain/scoring.py`
   (a test fails if you forget).
4. Add the per-kind SQL view / expression index in the storage projection, and the
   kind name to the API's `MemoryKindName` literal.
5. New kinds and vocabulary changes need an ADR — the model doc calls the data model
   stable for a reason.

Edges vs. reified relationships (ADR-0010): if a connection could ever need
confirming, contradicting, or dating, make it a `relationship` memory; otherwise use
a tier-1 `Link` from the closed relation vocabulary.

## How to add a projection

Implement the `Projection` protocol from `engram_events` (`handles`, `apply`, checkpoint
semantics), register it in the app wiring, and make sure `engram rebuild` replays it from
`global_seq = 0` deterministically.

## Architectural decisions (ADRs)

Significant decisions get an ADR in `docs/adr/` (copy `template.md`, number sequentially).
If your PR contradicts an accepted ADR, the PR must include a superseding ADR — that is a
feature, not bureaucracy: it forces the trade-off discussion to happen in writing.

## Commit & PR conventions

- Conventional Commits: `feat(core): …`, `fix(api): …`, `docs: …`, `chore: …`
  (checked in CI).
- Branch names: `feat/<slug>`, `fix/<slug>`, `chore/<slug>`.
- PRs need: green CI, a passing layering check, tests for behavior changes, and an ADR when
  a decision is architectural.

## Testing expectations

- `unit` tests are pure: aggregates and services tested against fake ports, no I/O.
- `integration` tests may touch a temp SQLite file or temp git repo (mark with
  `@pytest.mark.integration`).
- Event-sourced code has a house style: **given** a list of events, **when** a command,
  **then** assert the emitted events. Replay determinism is a CI-tested invariant.

## Code of Conduct

We follow the [Contributor Covenant](CODE_OF_CONDUCT.md). Be kind.
