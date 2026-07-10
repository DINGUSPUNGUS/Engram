# ADR-0002: Event sourcing from day 1

- **Status**: Accepted
- **Date**: 2026-07-10

## Context

The roadmap demands undo, rollback, audit ("which assistant wrote this?"), timelines,
conflict detection, decay scoring over access history, and PR-style approvals. Building
these on a mutable-row model means bolting a history table onto every feature, forever.

## Decision

State changes are appended domain events; current state is a fold. Concretely:

- Aggregates expose `decide_*` (validate → payloads) and `fold`/`evolve` (pure
  reconstruction). Services orchestrate: load → decide → wrap in envelopes → append →
  publish.
- The `events` table is append-only at the trigger level. Corrections are compensating
  events; undo appends, never rewrites.
- Every payload carries a `schema_version`; the kernel registry applies upcasters at read
  time so any historical log replays into current dataclasses. Shipped payload shapes are
  immutable.
- Optimistic concurrency via the per-stream sequence (`uq_events_stream_position`);
  losers get `StaleVersionError` (HTTP 409) and retry against fresh state.
- **Snapshots are reserved, not built**: at personal-memory scale, replaying a stream is
  microseconds. If profiling ever disagrees, snapshots are a pure read-side optimization
  that changes no contracts.

## Consequences

- Undo/replay/audit/timeline/analytics fall out structurally. ✔
- Unit testing becomes given-events / when-command / then-events. ✔
- Contributors must learn the idiom (mitigated in CONTRIBUTING.md), and event schema
  discipline is non-negotiable (mitigated by registry completeness tests + upcasters).
- The Proposal aggregate stores draft envelopes; if that proves heavier than needed, the
  recorded fallback is plain draft events with an approve/discard flag.

## Alternatives considered

- **CRUD + audit columns**: cheaper day 1, but every roadmap feature re-invents history.
- **CRUD now, ES later**: migrating a live store to ES is notoriously the worst of both.
