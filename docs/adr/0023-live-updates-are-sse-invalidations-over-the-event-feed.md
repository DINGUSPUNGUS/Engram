# ADR-0023: Live updates are SSE invalidation signals over the event feed; the log stays the source of truth

- **Status**: Accepted
- **Date**: 2026-08-05

## Context

The dashboard shows projection-derived state — counts, review queues, timelines — that
changes whenever an event is appended, including by other clients (the CLI, an MCP
assistant, the pipeline). Polling makes the UI stale by its interval and makes the Home
screen misreport a review queue that already moved.

engram has the pieces for something better and no decision recorded about using them.
`InProcessEventBus` delivers every appended envelope synchronously and in order to its
subscribers; projections already subscribe at startup. `EventStore` assigns a total
order via `global_seq` and `read_all(after=, limit=)` replays from any position. So a
live feed is available without new infrastructure — but pushing events to a browser
raises three questions no existing ADR answers: which transport, what the client is
allowed to *do* with a pushed event, and what happens across a disconnect.

The third question is the dangerous one. A push channel that clients treat as a state
feed becomes a second, weaker source of truth: miss a frame during a reconnect and the
UI silently diverges from the log, which is precisely the class of bug event sourcing
exists to eliminate.

## Decision

**1. Server-Sent Events, not WebSockets.**

`GET /api/v1/events/stream` is a thin shell over the existing feed. The traffic is
one-way (server → dashboard), so a bidirectional protocol buys nothing and costs a new
transport to secure, proxy, and test. SSE is plain HTTP: the existing CORS config,
`RequestContextMiddleware`, error handling and future auth apply unchanged, and
`EventSource` reconnects on its own.

**2. A stream message is an invalidation signal, not state.**

Each message carries the same `EventResponse` shape the paginated feed already returns
— `event_id`, `stream_id`, `stream_seq`, `global_seq`, `event_type`, `occurred_at`,
`provenance`. Payloads stay omitted, exactly as `GET /api/v1/events` omits them.

Clients react by **re-reading the affected projection through the normal endpoints**.
They must not fold pushed events into local state. This is ADR-0021's rule applied to
the stream: folding is a domain operation, the projection is the only state, and a UI
that reconstructs state from a socket is a second implementation of the fold that will
drift from the real one. The stream answers "something changed, and roughly what";
the read endpoints answer "what is true now".

**3. Reconnection is a catch-up query, not a buffer.**

Every message sets the SSE `id:` field to its `global_seq`. On reconnect the browser
sends `Last-Event-ID`, which the endpoint maps to `read_all(after=<seq>)` and replays
from the log before resuming live delivery. No server-side ring buffer, no
at-most-once window, no lost-update hole: the log is durable and totally ordered, so
catch-up is just a query. A client that has been away for a week gets correct results
by the same path as one that blinked, subject to a replay cap after which it is told
to re-read from scratch rather than served a partial history.

**4. The bus is a wakeup; the log is truth.**

The endpoint subscribes to `InProcessEventBus` only to learn *when* to look. What it
sends always comes from the store, ordered by `global_seq`. If the bus drops a
notification, the next one — or the heartbeat — still advances the cursor and the
client still converges. Correctness never depends on the bus delivering everything.

**5. Degradation is explicit.**

The in-process bus is process-local: under a future multi-process deployment, a worker
sees only its own appends. Because delivery already flows from the store by cursor,
that case degrades to periodic cursor polling behind the identical endpoint and the
identical client contract — a change in how the loop is woken, not in what clients
consume. Heartbeat comments keep intermediaries from closing idle streams, and
concurrent streams per process are capped (this is a local-first, single-user system;
an unbounded fan-out is a bug, not a feature).

## Consequences

- Home, Timeline, and the review queue reflect changes made by the CLI, an assistant,
  or the pipeline within a round trip, without polling every screen. ✔
- Determinism is untouched: no client-side folding exists to diverge, and replay
  semantics are unaffected because nothing about the stream is persisted. ✔
- Reconnect correctness falls out of the event log's existing guarantees rather than
  from stream-specific machinery that would need its own tests. ✔
- Every live update costs a follow-up read. That is the deliberate trade — an extra
  request per change in exchange for never maintaining a second copy of the fold. For
  a local-first single-user system the request is cheap; if it ever isn't, the fix is
  a coarser signal, never a richer one.
- SSE over HTTP/1.1 is subject to per-host connection limits. One stream per dashboard
  session, shared across views, not one per component.
- The endpoint holds an open connection per client, which is new for this API: tests
  must cover disconnect, reconnect-with-`Last-Event-ID`, and cap-exceeded.

## Alternatives considered

- **WebSockets.** Bidirectional framing for a one-way problem; a second transport to
  authenticate and proxy, and an invitation to send *commands* over the socket, which
  would route writes around the router layer and around Proposal → Review → Merge.
  Rejected.
- **Push full event payloads and let the client fold them.** Removes the follow-up
  read, at the cost of a second implementation of the domain fold living in
  TypeScript — the exact frontend business logic M7 forbids, and a permanent
  divergence risk. Rejected.
- **Server-side buffer with sequence-gap detection.** Reinvents durable ordered
  replay, which the event store already provides. Rejected.
- **Polling only.** Zero new surface and genuinely adequate today, but it makes
  staleness a property of the UI rather than of the data, and the Home screen's
  purpose is to be trusted at a glance. Kept as the documented fallback for
  multi-process deployments (§5) rather than as the default.
