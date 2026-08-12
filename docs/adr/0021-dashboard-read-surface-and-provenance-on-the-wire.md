# ADR-0021: The dashboard is another thin shell; M7 completes the v1 read surface and puts provenance on the wire

- **Status**: Accepted
- **Date**: 2026-08-05

## Context

M7 builds the first user interface over engram. ADR-0007 already settles what an
interface may do — parse input, call exactly one application service method, map the
result — and the dashboard is one more shell under that rule, not a new kind of thing.

Three capabilities M7 must present have no HTTP surface at all, although the services
behind them are complete:

- **Proposal detail.** `Proposal` folds `proposed_events` (the draft intents under
  review) and `merged_event_ids` (what the merge actually appended). Neither appears in
  `ProposalResponse`, and there is no `GET /api/v1/proposals/{id}` — only the list.
- **Proposal undo.** `Proposal.decide_undo` and `ProposalCommandService.undo_proposal`
  implement ADR-0018 §3 compensation, and `ProposalStatus.UNDONE` exists. No route
  reaches them; `POST /memories/{id}/undo` covers only the single-memory case.
- **Time travel.** The `MemoryHistory.state_at` port reconstructs a memory as of a
  timestamp or version. Nothing exposes it.

Worse for M7's purpose, the metadata that makes any of this *explainable* is dropped at
the boundary. Every event carries `EventEnvelope.provenance` — `actor`, `session_id`,
`detail` — and ADR-0019 §3 loads the entire pipeline explanation into `detail`. Yet
`EventResponse` projects `actor` alone and discards the rest, so the one field designed
to answer "where did this come from?" never leaves the process.

The freeze declared after M6 says milestones consume the architecture rather than
expand it. The question this ADR answers is whether completing the read surface counts
as expansion. It does not, and the roadmap already scoped it: M7 is "REST completeness
(all v1 endpoints live, timeline/undo over HTTP) **and** the dashboard."

## Decision

**1. The dashboard is an ADR-0007 shell and gets no exemption.**

It reaches the backend only through `@engram/api-client` (via
`apps/web/src/lib/api/client.ts`). No direct database access, no second HTTP client, no
domain state derived in the frontend. Folding events into state, deciding whether a
proposal is reviewable, computing effective confidence, or ordering a lifecycle are
domain operations; a component that does one of them is a bug in the same way a router
that does one is a bug.

**2. Missing surface is added as thin routes, one service call each.**

| Route | Delegates to |
| --- | --- |
| `GET /api/v1/proposals/{id}` | `ProposalQuery` / folded `Proposal` |
| `GET /api/v1/proposals/{id}/timeline` | the proposal's event stream |
| `POST /api/v1/proposals/{id}/undo` | `ProposalCommandService.undo_proposal` |
| `GET /api/v1/memories/{id}/at` | `MemoryHistory.state_at` |
| `GET /api/v1/stats` | existing projection counts + event-store head |
| `GET /api/v1/settings` | gateway capabilities, `VersionControl.status`, export paths |

Each is transport plumbing over behavior that already exists. None introduces a domain
concept, an event type, or a decision.

**3. Read models carry provenance.**

A `ProvenanceView` (`actor`, `session_id`, `detail`) is added to event and proposal
reads. This is projection of existing envelope metadata into the response, not new
metadata — ADR-0019 §3 already guarantees it is written, replayed byte-for-byte, and
folded by nothing.

**4. The escape hatch stays closed.**

When a view wants something the services cannot answer, the fix is a query method in
`engram-core` — never a computation in a router, and never one in a component. This is
ADR-0007's rule restated at the point where it is most tempting to break.

## Consequences

- The three interfaces stay honest: anything the dashboard can do, the CLI and MCP
  server can do, because all three call the same methods. ✔
- "Which assistant proposed this?" becomes answerable over HTTP for the first time,
  which is the precondition for the Observatory existing at all. ✔
- The OpenAPI drift check now guards a much larger surface — more schema churn in CI,
  and every new field is a permanent v1 commitment (breaking changes mean `/api/v2`).
- `Provenance.detail` is free-form and reaches clients unparsed. Consumers must treat
  it as untrusted, optional text; ADR-0022 fixes how the dashboard renders it.
- Six new routes is six more surfaces to keep thin. The review rule from
  CONTRIBUTING.md ("logic in a router is a bug") is doing real work here.

## Alternatives considered

- **Let Next.js server components call the Python services directly.** Collapses the
  dual-language boundary of ADR-0006 and gives the dashboard a private path that the
  CLI and MCP server do not have — the exact interface drift ADR-0007 exists to
  prevent. Rejected.
- **Derive draft intents in the frontend by replaying `/api/v1/events`.** This is
  domain folding in React, which M7 explicitly forbids; it also cannot work, because
  the event feed omits payloads by design and `proposed_events` never appears in it.
  Rejected.
- **A dedicated BFF or GraphQL layer for the dashboard.** A second wire contract to
  keep in sync with the first, and a natural home for exactly the view-shaped business
  logic this ADR is trying to keep out. The generated client plus the drift check
  already give end-to-end typing without it. Rejected.
- **Leave the surface as-is and descope the Observatory to what fits.** Honest, but it
  would ship a dashboard that cannot answer "why does this memory exist?" — the
  question ADR-0015 names as the difference between a memory tool and memory
  infrastructure people trust. Rejected.
