# Operations: Errors, Logging, Configuration

## Error handling

One hierarchy, defined in the domain (`engram_core/domain/errors.py`):

```
EngramError
├── ValidationError      # bad input / broken invariant        → 422 / exit 1
├── NotFoundError        # unknown or deleted aggregate        → 404 / exit 1
├── ConflictError        # contradicts current state           → 409 / exit 1
│   └── StaleVersionError  # optimistic concurrency loss       → 409 / exit 1
└── StorageError         # adapter failure the caller can't fix → 500 / exit 70
```

Rules:

- **Adapters translate inward**: SQLAlchemy/GitPython/OS exceptions become `EngramError`
  subclasses before crossing a port. Library exceptions never reach services.
- **Interfaces map outward exactly once**: the API in `engram_api/errors.py` (RFC 9457
  problem+json), the CLI to exit codes (0 ok · 1 expected failure · 2 usage · 70 internal).
- **No swallowing**: nothing in domain/application catches-logs-and-continues. If a layer
  can't handle an error, it doesn't touch it.

## Logging

- **structlog** everywhere above the domain. The domain layer never logs — its audit
  trail *is* the event log.
- Dev: pretty console. Prod: JSON lines. Switch: `ENGRAM_LOG_FORMAT=console|json`.
- The request id (accepted or minted per request) is bound via contextvars, so every log
  line of a request correlates. Same pattern applies to CLI invocations later.
- Caution: event payloads may contain personal memory content. Log envelope *metadata*
  (type, stream, seq), never payload bodies, at INFO and above.

## Configuration

- **pydantic-settings**, in apps only (`engram_api/config.py`). engram-core is
  config-free by construction — values arrive through constructors.
- Precedence (highest wins): explicit init kwargs → environment variables → `.env` →
  `~/.config/engram/config.toml` → defaults.
- Everything defaults to a working zero-config local setup under `~/.engram`.

## Environment variables

| Variable | Default | Meaning |
| --- | --- | --- |
| `ENGRAM_DATA_DIR` | `~/.engram` | Root for all engram state |
| `ENGRAM_DB_PATH` | `<data>/engram.db` | SQLite: event log + projections |
| `ENGRAM_EXPORT_REPO` | `<data>/memory` | Git repo receiving the markdown/NDJSON export |
| `ENGRAM_API_HOST` / `ENGRAM_API_PORT` | `127.0.0.1` / `8000` | API bind (loopback: see security.md) |
| `ENGRAM_LOG_LEVEL` / `ENGRAM_LOG_FORMAT` | `INFO` / `console` | Logging |
| `ENGRAM_ENV` | `development` | `development · production · test` |
| `NEXT_PUBLIC_API_URL` | `http://127.0.0.1:8000` | Where the browser reaches the API |

`.env.example` at the repo root is the canonical, commented list — keep it in sync with
this table in the same PR.
