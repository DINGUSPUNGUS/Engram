# ADR-0006: One monorepo, two languages (Python backend, TypeScript frontend)

- **Status**: Accepted
- **Date**: 2026-07-10

## Context

The engine wants Python (FastAPI, SQLModel, the ML/embeddings ecosystem for later phases);
the dashboard wants the React ecosystem (Next.js 15, shadcn/ui). Splitting repos would
decouple the API contract from its consumer and double release coordination.

## Decision

One repository. pnpm + Turborepo orchestrate everything; Python packages are uv workspace
members that each carry a minimal `package.json` shim (`"test": "uv run pytest tests"`),
so `turbo lint/typecheck/test` runs both worlds with caching. The OpenAPI schema is the
bridge: generated client, committed contract, CI drift check.

Tooling boundary is absolute: Ruff/mypy/pytest never touch TS; Biome/tsc/vitest never
touch Python. Turbo is the only thing that sees both.

## Consequences

- Contract changes and their consumers land in one PR. ✔
- Contributors need Node *and* uv installed (`pnpm install && uv sync --all-packages` is
  the whole setup); CI path-filtering spares frontend-only PRs the Python matrix and vice
  versa.
- Turbo's Python support is shim-based, not native — inputs are declared per task in
  `turbo.json` so caching stays correct.
- turbo is pinned exactly (2.5.4): newer prebuilt binaries crash with
  STATUS_ILLEGAL_INSTRUCTION on CPUs lacking newer instruction sets. Revisit periodically.
