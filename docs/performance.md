# Performance

**M9 performance pass.** Measurement first, optimization only where measurement justified
it (`scripts/benchmark_perf.py`) — consistent with ADR-0002's own stance that snapshotting
is reserved as "a pure optimization... if replay cost ever demands it," not built ahead of
evidence.

## Methodology

`scripts/benchmark_perf.py` builds one scratch space through the real CLI composition root
(`engram_cli.runtime.build_runtime` — the same code every `engram` invocation runs, not a
shortcut), populates it with a synthetic dataset at the scale
[architecture.md](architecture.md)'s own self-critique names ("At personal-memory scale
(thousands of events, not billions) replay cost is a non-issue for years"), and times every
operation named in the M9 scope: event append, projection rebuild, differential-rebuild
fidelity verification (`status --verify`), memory search (five representative query
shapes), proposal open/merge/undo, export, import (`--restore`), and dashboard API response
times (a real ASGI `TestClient` against the same populated store — ADR-0007's "no domain
logic in the API" means these numbers are the same code path a real HTTP request runs).

Run it yourself: `uv run --package engram-cli python scripts/benchmark_perf.py --n 1000`.
Results are written to `evaluations/results/performance_baseline.json` (git-ignored —
machine-dependent, not a committed regression gate the way `evaluations/results/
baseline.json` is for AI quality) and printed as a table.

SSE catch-up cost was audited by reading `apps/api/src/engram_api/routers/v1/events.py`
rather than measured with a live client: reconnect replay is capped at `_REPLAY_CAP = 5000`
events, with an explicit `resync` signal (ADR-0023 §3) sent instead of an unbounded replay
beyond that — confirmed already bounded, not a full-log-scan-shaped risk, so no separate
number is meaningful here.

## Results (N = 1,000 memories)

~2,200 total events, single Windows dev machine — absolute numbers are machine-dependent;
relative shape and the before/after deltas are the point. After both fixes below
(`synchronous=NORMAL`; deferred search hydration):

| Operation | Mean | p95 | Notes |
| --- | --- | --- | --- |
| Event append (create) | 40.2ms | 52.0ms | one event, one projection apply each |
| Event append (tag update) | 58.1ms | 66.9ms | loads the stream first (cheap: 1-2 events) |
| Projection rebuild (full, ~2,200 events) | 82.7s | — | see "not fixed" below |
| `status --verify` (differential rebuild) | 39.5s | — | one projection's worth of the above |
| Memory search | 310.7ms | 483.6ms | was 6,435ms — see fix #2 |
| Proposal open | 33.4ms | 42.8ms | |
| Proposal merge | 95.1ms | 102.9ms | |
| Proposal undo | 1,725.8ms | 1,930.4ms | not fixed this pass — see below |
| Export (full, 1,000 memories) | 22.3s | — | one-time full export |
| Import (`--restore`, ~2,200 events) | 12.7s | — | |
| Dashboard `GET /memories` (list) | 254.6ms | 265.5ms | no free-text term |
| Dashboard `GET /memories/{id}` | 33.3ms | 35.3ms | |
| Dashboard `GET /stats` | 45.6ms | 35.9ms | |
| Dashboard `GET /search?q=` | 489.9ms | 527.4ms | was 10,600ms — see fix #2 |

## What the measurements found

**`synchronous=FULL` (SQLite's default) was the actual bottleneck, not the event-sourced
architecture.** Every event append and every projection `apply()` commits its own
transaction — the same per-event atomicity P1 hardening (this milestone) relies on, and
deliberately left unchanged. At the default `synchronous=FULL`, WAL mode still fsyncs on
every one of those commits: measured directly (raw `sqlite3`, isolated from any engram
code) at ~11–20ms per commit on this machine. A full `engram rebuild` replaying a few
thousand events, each triggering one-to-several such commits across the projections that
handle it, was measured heading toward minutes, not seconds — squarely the "known
O(stream-length) operations and full-log replay paths" this milestone asked to watch.

**Fix:** `synchronous=NORMAL`, the documented-safe pairing with `journal_mode=WAL`
(`libs/engram-storage-sqlite/src/engram_storage_sqlite/event_store.py`). Measured directly:
raw commit latency drops from ~11–20ms to ~0.3ms — no other change. SQLite's own
documentation is explicit that `NORMAL`+WAL keeps the database file itself safe from
*corruption* even on power loss mid-write; what's given up is a guarantee that the single
most-recent commit or two survives a power loss in that exact instant (full durability
against an ordinary application crash is unaffected either way). Right trade-off for
local-first desktop software with one writer; wrong one for a server of record — see
[architecture.md](architecture.md) self-critique #12.

**Search built a full read model — tags, evidence, links, retention scoring, several
queries each — for every SQL-matched candidate, then discarded all but `limit` of them.**
`SqliteQueryEngine.query()` fetched every row matching the cheap SQL filters, called
`_read_model()` (the several-extra-queries-per-row hydration `get`/`list_memories` also
use) on *all* of them, filtered by `confidence`/`stale`, ranked, and only then sliced to
the page actually requested. A free-text search matching most of a 1,000-memory space
(plausible: several hundred to a thousand matches is not an edge case) measured at
**6,435ms mean** — the single worst number this pass found, worse than the fsync issue
above.

**Fix:** defer full hydration until after filtering, ranking, and pagination
(`libs/engram-storage-sqlite/src/engram_storage_sqlite/query_engine.py`,
`_filter_and_rank`). `effective_confidence` — the only thing `confidence>`/`is:stale`
filtering needs — depends only on a record's own `confidence`/`kind`/`last_confirmed_at`
columns, never on tags/evidence/links, so computing it directly per candidate (zero extra
queries) and hydrating only the final `limit`-sized page was a safe, contained change, not
a redesign of the query engine's documented SQL-filters-vs-derived-filters split
(unchanged). Measured: **310.7ms mean** — ~20x. Proven independent of timing noise by
`test_hydration_count_matches_the_page_not_the_match_count`: hydration is called exactly
`limit` times regardless of how many rows the SQL filters matched.

**Found, not fixed this pass: `undo_proposal` scans the event log from the beginning to
locate the events it's compensating**, and that cost does not shrink after the two fixes
above (**1,726ms mean**, unmoved by either). Root cause, read directly from
`engram_core.application.commands.proposal_commands.ProposalCommandService.
_affected_streams`: to find a merged event's stream, it walks `store.read_all` forward in
batches of 500 from the log's start until every target `event_id` turns up — deliberately,
per its own docstring, "bounded by the log size," i.e. O(log size) by design, not O(1) or
O(affected stream size). A merge near the end of a long log means scanning almost the
whole thing to undo it. `events.event_id` already carries a `unique=True` constraint
(migration 0001) — SQLite indexes that for free — so a direct `WHERE event_id IN (...)`
lookup is available and would very likely fix this the same way the search fix did.
**Not implemented in this pass**: unlike the query-engine fix, this touches the
`EventStore` port itself (`engram_events.store.EventStore`) — the single narrowest,
most foundational, most-relied-upon interface in the whole system, used by every adapter
and every command service. A same-day change to it, on top of everything else in this
pass, carries more regression risk than the smallest-fix discipline this milestone asks
for accepts casually. Recorded here as the clear, concrete, ready-to-implement next
performance candidate — not guessed at, not spec'd loosely: the fix is a new
`EventStore.read_by_ids(event_ids)` method plus rewriting `_affected_streams` to call it
instead of walking from the log start.

**Not fixed, and not going to be:** `snapshots`, additional indexes beyond the one that
already exists on `event_id`, a cache layer, or background workers. Neither identified
issue needed any of them — both were pure code-path fixes (a pragma; a reordered pipeline)
within already-existing schema and architecture. If a future measurement at a materially
larger scale shows replay cost becoming a real problem on its own terms, ADR-0002 already
reserves snapshotting as the next lever to pull — still not pulled here.

**Rebuild/verify (82.7s / 39.5s at ~2,200 events) did not meaningfully improve from either
fix**, as expected — they're bound by Python/SQLAlchemy per-event-per-projection call
overhead (session construction, ORM row mapping), not by fsync (already removed) or by
search's N+1 pattern (rebuild doesn't call `query()`). This is the "known
O(stream-length) ... full-log replay path" the milestone asked to watch, confirmed still
linear and still the slowest operation measured by a wide margin. No fix attempted: every
option that would meaningfully cut per-event overhead here (batched multi-event commits
across projections, a different ORM access pattern) is a real change to the already-proven
P1 per-event atomicity guarantee, which is exactly the "do not redesign completed
subsystems without concrete evidence" line — and at ~40s/1,000 events, this stays a
background `engram rebuild`/`--verify` cost on personal-memory-scale spaces, not (yet) a
blocking one. Flagged, not acted on.

## Known limitations of this pass

- One machine, one run per N. No statistical confidence interval beyond the min/mean/p95
  the harness reports per operation; treat absolute numbers as indicative; the relative
  before/after deltas for both fixes are the load-bearing evidence.
- The synthetic dataset uses one memory kind (`fact`) throughout for simplicity — kind mix
  was not the variable under test.
- `proposal_undo`'s cost is unresolved, documented above, not implemented.
