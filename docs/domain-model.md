# Domain Model

> **The model of record is [memory-model.md](memory-model.md)** — the twelve kinds, the
> justification spine, lifecycle, confidence, decay, conflict resolution, and graph
> semantics all live there. This document covers the *mechanics*: how the model is
> realized as aggregates, values, and ports. Code of record:
> `libs/engram-core/src/engram_core/domain/`.

## MemorySpace

One user-owned memory set: an event log, its projections, and an export repository. The
consistency boundary — everything below lives inside one space.

## Memory (the one aggregate, ADR-0008)

Owns the mechanism for all twelve kinds: identity (`MemoryId`, UUIDv7, immutable),
event stream, narrative fields (`slug`/`title`/`content`), typed `attributes`
(validated via the `KindRegistry`), the justification spine (`confidence`,
`last_confirmed_at`, `evidence`, `importance` signals, `lifetime`, `visibility`),
tier-1 `links`, lifecycle flags, and `version` (optimistic-concurrency token).

- Reconstruction: `fold` / `evolve` — pure functions over the stream.
- Commands: `decide_create`, `decide_edit` (narrative), `decide_update_attributes`
  (kind schema), spine commands (`decide_confirm`, `decide_contradict`,
  `decide_add_evidence`, `decide_adjust_importance`, `decide_set_visibility`,
  `decide_set_lifetime`), organization (`decide_tag`, `decide_link`,
  `decide_merge_from`), lifecycle (`decide_archive/restore/delete`,
  `decide_record_access`).
- Staleness is **not** a field: it is derived by the scoring projection
  (effective confidence below the kind threshold, memory-model.md §5).

## Kind schemas (`domain/kinds.py`)

Twelve frozen dataclasses (`FactAttributes` … `RelationshipAttributes`) with closed
`StrEnum` vocabularies, registered in the `KindRegistry` with `schema_version` and
upcasters — the same evolution discipline as events. `build_kind_registry()` is the
canonical registration, mirrored by `build_registry()` for events.

## Proposal (aggregate)

PR-style review: draft events targeting memory streams, status
`draft → pending → approved/rejected`, `approved → merged`. Merge re-validates against
current target streams; a moved target is `StaleVersionError` (409), never a silent
overwrite. Proposals are also the vehicle for automatic pruning (ADR-0011) and, later,
memory extraction — automation proposes, events decide.

## Values (`domain/values.py`)

`MemoryId`/`ProposalId` (UUIDv7 NewTypes) · `Slug` (constrained alphabet = traversal
guard) · `MemoryKind` (12) · `LinkRelation` (10, closed) · `Link` · `EvidenceRef` +
`EvidenceType` · `Lifetime` + `RetentionPolicy` · `Visibility` · `ImportanceSignals` ·
`validate_confidence`. All frozen, all validated at construction.

## Tunables (`domain/scoring.py`)

Confidence priors, confirm/contradict weights, per-kind half-lives and staleness
thresholds, retention weights, pruning threshold (ADR-0009: constants in one module,
scores derived in projections, retunable via `engram rebuild`).

## Ports (what the domain needs from the world)

| Port | Side | Canonical adapter |
| --- | --- | --- |
| `MemoryRepository`, `ProposalRepository` | write | engram-storage-sqlite |
| `MemoryQuery` (kind/tag/stale filters, visibility-enforced) | read | engram-storage-sqlite |
| `QueryEngine` (the query language, ADR-0016; `supports_vectors` capability flag) | read | engram-storage-sqlite (FTS5; vectors in M5) |
| `MemoryHistory` (time travel: `state_at` a version or instant) | read | engram-storage-sqlite |
| `EmbeddingProvider` | — | none (interface reserved; milestone M5) |
| `MarkdownSync`, `VersionControl` | export | engram-export-git |
| `Clock` | ambient | app-provided |
| `EventStore`, `EventBus`, `Projection` | kernel | engram-storage-sqlite / in-process bus |
