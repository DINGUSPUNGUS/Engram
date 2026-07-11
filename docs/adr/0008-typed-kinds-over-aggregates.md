# ADR-0008: Twelve typed memory kinds as versioned schemas over one aggregate

- **Status**: Accepted
- **Date**: 2026-07-11

## Context

Memories must not be markdown blobs: `Project.status`, `Person.aliases`,
`Preference.strength` need to be structured, validated, queryable fields — that is what
makes search, graph traversal, dedup, and pruning tractable at 100k memories. The obvious
DDD reading — one aggregate class per kind — would multiply the event-sourcing mechanism
(streams, fold/decide, repositories, undo, lifecycle, API surface) by twelve, and kind #13
would be a subsystem, not a schema.

## Decision

One `Memory` aggregate owns the *mechanism*: identity, event stream, metadata spine,
links, lifecycle, versioning. Each kind contributes only its *shape*:

- A frozen attributes dataclass per kind (`ProjectAttributes`, `PersonAttributes`, …)
  with closed `StrEnum` vocabularies, registered in a **KindRegistry** with a
  `schema_version` and upcasters — the exact pattern the event registry uses.
- Commands validate attributes against the registered schema before emitting
  `MemoryCreated` / `MemoryAttributesUpdated`. The store persists only schema-valid data.
- Queryability comes from the projection: JSON `attributes` column + expression indexes
  on hot fields + one SQL view per kind exposing attributes as typed columns.
- `kind` is immutable after creation; misclassification is fixed by supersede, keeping
  history honest.

## Consequences

- "First-class domain objects" in every way that matters — typed fields, validation,
  per-kind queries/views — at the cost of one dataclass per kind instead of one
  subsystem per kind. ✔
- Adding a kind: dataclass + registration + view + ADR if vocabularies change. ✔
- Attribute evolution reuses the upcaster discipline contributors already learn for
  events — one mental model. ✔
- JSON-in-SQLite for attributes trades a little raw query ergonomics for schema agility;
  mitigated by views and expression indexes, revisitable per-kind (a hot kind can get a
  physical projection table later without touching the domain).

## Alternatives considered

- **Twelve aggregates**: maximal type safety, catastrophic mechanism duplication.
- **EAV attribute table**: uniform but destroys type safety and query readability.
- **Free-form JSON without registry**: schema drift within a year; rejected outright.
