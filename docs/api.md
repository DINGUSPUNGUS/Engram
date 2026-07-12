# REST API

Base: `http://127.0.0.1:8000` (loopback by default). Versioned under `/api/v1`; breaking
wire changes mean a `/api/v2` package, never edits to v1. The OpenAPI document exported by
`python -m engram_api.export_openapi` is the contract — `packages/api-client` is generated
from it and CI fails on drift.

## Conventions

- Plural-noun resources, kebab-case paths, snake_case JSON fields, UUIDs in paths.
- Cursor pagination: `?cursor=<opaque>&limit=<n>`; responses carry `next_cursor`.
- Errors are RFC 9457 `application/problem+json`, always. Mapping (one place,
  `engram_api/errors.py`): `ValidationError→422`, `NotFoundError→404`,
  `StaleVersionError/ConflictError→409`, `StorageError→500`, stubs→501.
- Optimistic concurrency: read models carry `version`; edits send `expected_version`;
  a stale token is a 409 — re-read and retry.
- `X-Request-Id` accepted or minted, always echoed. `X-Engram-Actor` names the calling
  assistant for event provenance (until the auth milestone replaces it).

## Endpoints

| Method & path | Purpose |
| --- | --- |
| `GET /healthz` · `GET /version` | Liveness, version |
| `POST /admin/rebuild` | Replay the log through all projections (202) |
| `GET /api/v1/memories` | List (filters: `memory_type`, `tag`, `include_archived`; paginated) |
| `POST /api/v1/memories` | Create → 201 |
| `GET /api/v1/memories/{id}` | Current state |
| `PATCH /api/v1/memories/{id}` | Sparse edit (`expected_version` required) |
| `DELETE /api/v1/memories/{id}` | Tombstone → 204 (history persists) |
| `GET /api/v1/memories/{id}/timeline` | Full event history of one memory |
| `POST /api/v1/memories/{id}/undo` | Append the compensating event |
| `GET /api/v1/proposals` · `POST /api/v1/proposals` | Review queue |
| `POST /api/v1/proposals/{id}/approve·reject·merge` | Review lifecycle; merge conflicts → 409 |
| `GET /api/v1/search?q=` | The query language (ADR-0016): `q` takes operators + free text, identical to `engram search` |
| `GET /api/v1/events?after=&limit=` | Audit feed over the raw log |

## Client generation

```sh
pnpm gen:client   # exports openapi.json, regenerates packages/api-client/src/generated
```

The web dashboard consumes only `@engram/api-client` (via `apps/web/src/lib/api/client.ts`)
so request/response types are end-to-end checked.
