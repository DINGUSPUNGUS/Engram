# ADR-0005: Hexagonal layering, enforced by CI

- **Status**: Accepted
- **Date**: 2026-07-10

## Context

A decade-scale open-source project accumulates contributors who haven't read the design
docs. Unenforced architecture erodes one convenient import at a time.

## Decision

Four layers, imports point inward only:

```
apps (api, cli, mcp, web)          — interface: parse, delegate, map
adapters (storage-sqlite, export-git) — implement ports with real tech
engram-core                        — domain + application; pure
engram-events                      — kernel; imports nothing of ours
```

Enforcement is mechanical, not cultural:

- `import-linter` layers contract in root `pyproject.toml`, run by `pnpm run
  lint:architecture` and CI. A violating PR fails.
- Ports are `typing.Protocol` (structural): adapters don't import an ABC from core to
  inherit — they just match the shape, keeping even the *dependency direction of
  interfaces* inward.
- Each app has exactly one composition root (`dependencies.py`) where implementations are
  named. Constructor injection everywhere else; no service locators, no globals, no
  framework magic in core.

## Consequences

- Everything is replaceable: SQLite, GitPython, FastAPI, the bus — each swap touches one
  adapter or one composition root. ✔
- Core is testable with fakes at memory speed. ✔
- Some ceremony (DTOs at boundaries, ports for trivial things like `Clock`) — accepted as
  the price of a codebase that still has boundaries in year five.
