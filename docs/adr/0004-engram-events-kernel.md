# ADR-0004: A zero-dependency events kernel; subsystems communicate through events

- **Status**: Accepted
- **Date**: 2026-07-10

## Context

Storage, search, export, decay, extraction — every subsystem reacts to the same state
changes. Direct calls between subsystems (storage calls search calls export…) braid them
into a monolith where adding a consumer means editing every producer.

## Decision

- A dedicated kernel package, **`libs/engram-events`**, at the bottom of the dependency
  graph: event envelope, type registry with `schema_version` upcasting, payload serde,
  and the `EventStore` / `EventBus` / `Projection` protocols. It imports nothing from
  engram and never will.
- **Writes fan out through the bus**: services append to the store, then publish;
  projections subscribe. Adding a consumer (new index, exporter, webhook) is a new
  `Projection` registered at the composition root — no producer changes.
- **Reads do NOT go through the bus.** Query services call projections synchronously.
  The bus is not RPC; routing reads through events would be ceremony without benefit.
- The default bus is **in-process and synchronous** (deterministic, transactional-ish,
  debuggable). Async/queued buses are future implementations of the same protocol,
  admitted only with profiling evidence.

## Consequences

- Subsystems stay independently replaceable; the plugin architecture (milestone M8)
  is "third-party projections + adapters", already shaped. ✔
- One more package to version — trivial against the decoupling it buys.
- Discipline required: the layering contract (import-linter) keeps the kernel clean.
