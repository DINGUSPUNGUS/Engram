# Naming Conventions & Coding Standards

## Naming

| Thing | Convention | Example |
| --- | --- | --- |
| Python dist / import package | `engram-*` / `engram_*` | `engram-core` / `engram_core` |
| TS package | `@engram/*` | `@engram/api-client` |
| Modules, functions, variables (py) | `snake_case` | `memory_relpath` |
| Classes, aggregates, events | `PascalCase` | `MemoryCommandService` |
| Events | `<Noun><PastTenseVerb>` — facts, not commands | `MemoryCreated` |
| Ports | Capability noun, no `I` prefix | `SearchIndex`, `Clock` |
| Adapters | `<Tech><Port>` | `SqliteEventStore`, `GitVersionControl` |
| REST paths / JSON fields | kebab-case / `snake_case` | `/api/v1/memories`, `next_cursor` |
| TS variables / components | `camelCase` / `PascalCase` | `apiClient`, `DashboardPage` |
| Env vars | `ENGRAM_*` | `ENGRAM_DB_PATH` |
| Branches | `feat|fix|chore|docs/<slug>` | `feat/event-store` |
| Commits | Conventional Commits | `feat(core): memory aggregate fold` |
| Slugs (domain) | `^[a-z0-9]+(-[a-z0-9]+)*$`, ≤ 80 | `kahnya-branding` |

## Python standards

- **Ruff** is the only linter/formatter (config in root `pyproject.toml`; line 100;
  rules E/W/F/I/UP/B/SIM/TC/TID/RUF). No Black, no isort, no flake8.
- **mypy `strict = true`** on all `src/` trees. Untyped defs do not merge.
- Frozen dataclasses for values and event payloads; `StrEnum` for closed vocabularies;
  `NewType` for ids; `Protocol` for ports (structural, no inheritance requirement).
- Docstrings state contracts (raises, invariants), not restatements of the signature.
- No `# type: ignore` without an issue link. No `except Exception` outside adapters.

## TypeScript standards

- **Biome** is the only linter/formatter (`biome.json`; 2-space, 100 cols, double quotes).
- `strict: true` plus `noUncheckedIndexedAccess`. No `any` that isn't quarantined.
- No default exports except where Next.js requires them (pages, layouts, configs).
- Server Components by default; `"use client"` is an opt-in with a reason.
- Internal packages export TS source (`exports: "./src/index.ts"`); Next transpiles.

## Architectural rules (CI-enforced)

1. Imports point inward (`import-linter` layers contract).
2. State changes are events; reads are synchronous projection queries.
3. Interface layers contain no logic.
4. Every shipped event payload shape is immutable — evolve via `schema_version` + upcaster.
5. Generated files (`packages/api-client/src/generated`, `openapi.json`) are never edited
   by hand.
