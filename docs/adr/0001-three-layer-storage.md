# ADR-0001: SQLite is canonical runtime state; markdown is the portable representation; git is history

- **Status**: Accepted
- **Date**: 2026-07-10

## Context

engram needs versioning, portability, *and* rich querying (semantic search, graph
traversal, decay scoring, duplicate detection, analytics). An earlier draft made the git
repo of markdown files the single source of truth with SQLite as a derived index. Review
concluded that this conflates three concerns: git is phenomenal at history and mediocre at
querying knowledge; databases are phenomenal at querying and mediocre at portability.

## Decision

Three canonical layers, one per concern:

1. **Event log** (SQLite `events` table): the system of record. Append-only, enforced by
   triggers.
2. **SQLite projections**: canonical *runtime state*. All queries are database queries.
   Every projection is disposable and rebuildable by replay.
3. **Markdown + git export**: canonical *portable representation and history*. An export
   projection writes one markdown file per memory and appends NDJSON event shards under
   `.engram/events/`; commits are batched with descriptive messages.

Portability invariant: `git clone` + `engram rebuild` reconstitutes the database
losslessly. External file edits enter the system only through the reconciler
(`MarkdownSync` port), which turns them into events — files never write to state directly.

Concurrency note: SQLite runs in WAL mode; stream appends are optimistic-concurrency
checked; the export repo takes a write lock around commits. If multi-process contention
grows, a small daemon owns the space (topology change — the ports don't move).

## Consequences

- Search/graph/decay/analytics are ordinary SQL problems. ✔
- Undo/audit/replay come from the log, not from git plumbing. ✔
- The markdown repo stays clean for humans (state files, not event noise in filenames). ✔
- Two-way markdown sync becomes the hardest subsystem (accepted; isolated in one adapter,
  deferred to roadmap phase 4; fallback: export-only + proposals for external edits).
- Reserved names for later projections: `memory_fts` (FTS5), `memory_vectors` (sqlite-vec).

## Alternatives considered

- **Git-canonical, SQLite-derived** (the original draft): simpler portability story, but
  every interesting query fights the storage model, concurrent writers fight the working
  tree, and PR-approvals force git semantics onto users. Rejected by design review.
- **Postgres**: not local-first; SQLite's in-process, zero-daemon nature is the point.
