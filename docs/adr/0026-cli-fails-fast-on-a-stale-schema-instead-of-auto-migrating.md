# ADR-0026: The CLI fails fast on a stale schema instead of auto-migrating

- **Status**: Accepted
- **Date**: 2026-08-14

## Context

engram's SQLite schema evolves via Alembic migrations (5 as of this writing,
`libs/engram-storage-sqlite/migrations/versions/`). Event payload schemas,
memory-kind attribute schemas, and proposal draft schemas already have a real,
tested versioning + upcasting mechanism (`engram_events.registry`,
`engram_core.domain.kinds`, `engram_core.application.commands.drafts`) — a
historical event of any age always deserializes and replays correctly. The
gap this ADR closes is different: the SQLite *DDL* schema itself, and what
happens when a database created by an older `engram` binary is opened by a
newer one.

`engram init`'s own docstring already says "create (or upgrade)" — running
Alembic's `upgrade_to_head` is the documented, sanctioned upgrade action, and
it is idempotent (reapplies only pending migrations). But nothing enforced
it: `apps/cli/src/engram_cli/runtime.py`'s `build_runtime` only checked that
the database *file* existed, never that its *schema* was current. Confirmed
empirically (M9 audit): pointing a current binary's `engram add`/`list` at a
database stamped one migration behind head reproduces
`sqlite3.OperationalError: no such column: memories.access_count` — a raw
SQL exception with the SQL statement and bound parameters dumped to the
terminal, no mention of "run a migration" anywhere. The existing
per-projection transactional-commit guarantee (P1 §2 hardening) still held —
no phantom checkpoint was left, and the event itself, since `events` is one
table untouched since migration 0001, stayed durably in the log — but the
failure mode was confusing, not actionable, and would repeat on every
subsequent command until the user happened to think to re-run `engram init`.

The API composition root (`apps/api/src/engram_api/runtime.py`) already
handles this differently and correctly: it calls `upgrade_to_head`
unconditionally on every process start, documented there as a deliberate
CLI/API difference ("a server that cannot serve a fresh data directory is
not local-first, and Alembic upgrades are idempotent"). That leaves the CLI
as the one place actually missing a decision.

## Decision

The CLI does not auto-migrate. Opening a database whose applied Alembic
revision is behind this build's migration head raises a clear `StorageError`
identifying the current and expected revisions and naming the exact fix:
`engram init` to upgrade the schema in place, then `engram rebuild` to
re-project the (untouched) event log into it.

Mechanism: `engram_storage_sqlite.migrate.require_current_schema(db_path,
engine)`, called from `engram_cli.runtime.build_runtime` immediately after
opening the database, before any command's actual logic runs. It compares
Alembic's `MigrationContext.get_current_revision()` against
`ScriptDirectory.get_current_head()` — read-only, runs no migration itself.

Auto-migrating from inside `build_runtime` (mirroring the API) was
considered and rejected for the CLI specifically: every other place a
mutation happens in this codebase requires an explicit, named user action —
proposals need an explicit `approve`/`merge`, plugin discovery grants no
trust without an explicit `enable`, a prompt version bump is explicit. A
CLI command silently rewriting the user's on-disk database schema as a side
effect of `engram list` breaks that pattern for the one artifact users are
told to treat like a password-manager vault (docs/security.md). The API
process is different in kind: it has no notion of "the user is about to
type a command," so auto-upgrade-on-start is the only sensible boundary
there, and that decision predates this ADR and is unchanged by it.

## Consequences

- A newer `engram` binary opened against an older `~/.engram` now fails with
  one clear, actionable message instead of a raw SQL traceback repeated on
  every command. ✔
- The sanctioned recovery is exactly the CLI's own existing "create or
  upgrade" framing of `engram init` — no new command, no new concept. ✔
- Confirmed via `apps/cli/tests/test_cli_schema_upgrade_e2e.py`: a database
  built at schema 0004 with a real event already logged, then upgraded via
  `engram init` and re-projected via `engram rebuild`, reaches state
  identical to what a fresh, always-current install would have produced —
  the old-state → upgrade → rebuild → equivalent-state property this ADR
  exists to guarantee.
- The check costs one `alembic_version` read per CLI invocation — negligible
  next to the command it precedes.
- Does not cover application-level config (env var renames/removals): no
  such change has ever shipped in this pre-1.0 project, so there is nothing
  yet to migrate. A real instance would need its own decision, not a
  preemptive mechanism built ahead of a concrete case.

## Alternatives considered

- **Auto-migrate on every CLI invocation, mirroring the API.** Rejected:
  the CLI's whole design language is explicit user action before any
  mutation of durable state; the API has no equivalent moment to defer to.
- **Detect drift but only warn, still proceed.** Rejected: a stale schema's
  proceeding is exactly what produces the raw `OperationalError` this ADR
  exists to prevent — warning and then failing anyway two lines later isn't
  materially better than failing immediately with a clear message.
- **Version the SQLite schema separately from Alembic's own revision
  tracking (e.g. a custom `schema_version` row).** Rejected: Alembic already
  *is* the schema version ledger (`alembic_version` table); adding a second,
  parallel version marker is exactly the kind of second source of truth
  ADR-0025 already argued against in the adjacent projection-fidelity
  decision, for the same reason — it can itself drift from what the schema
  actually is.
