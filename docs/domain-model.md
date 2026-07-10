# Domain Model

Domain-driven, event-sourced. Aggregates validate commands and emit events; state is a
fold over the stream. Code of record: `libs/engram-core/src/engram_core/domain/`.

## MemorySpace

One user-owned memory set: an event log, its projections, and an export repository. The
consistency boundary — everything below lives inside one space. Multi-space (work vs
personal) and multi-user workspaces are roadmap items; nothing in the model assumes a
single space, only a single space *per store*.

## Memory (aggregate root)

| Field | Type | Notes |
| --- | --- | --- |
| `id` | `MemoryId` (UUIDv7) | Immutable identity (ADR-0003). Time-ordered for index locality. |
| `slug` | `Slug` | Mutable, human-friendly handle. `^[a-z0-9]+(-[a-z0-9]+)*$`, ≤ 80 chars — the constrained alphabet doubles as the exporter's path-traversal guard. |
| `title`, `content` | `str` | Content is markdown. |
| `memory_type` | `MemoryType` | `fact · preference · project · reference · episodic` — also the export directory. |
| `tags` | `frozenset[str]` | Normalized lowercase. |
| `links` | `tuple[Link, ...]` | Typed directed edges (below). |
| `salience` | `Salience` | created / last-accessed / access-count. **Inputs only** — the decay algorithm is roadmap phase 8 and can be computed retroactively from `MemoryAccessed` events. |
| `archived`, `deleted` | `bool` | Soft states. Deleted = tombstoned; the stream persists. |
| `version` | `int` | Last applied `stream_seq`; the optimistic-concurrency token. |

Commands (`decide_*`) → events: create, edit, tag, link, merge_from, archive, delete,
record_access. Reconstruction: `fold`/`evolve` (pure).

## Link

`(target_id, relation)` where relation ∈ `relates_to · supersedes · derived_from ·
contradicts`. Stored on the source memory's stream (`MemoryLinked`), materialized into the
`links` projection table for graph traversal. `supersedes` and `contradicts` are the
hooks for future dedup/consistency tooling.

## Proposal (aggregate root)

PR-style review for memory changes — how automatic memory extraction stays trustworthy:
an assistant proposes, the user approves.

| Field | Notes |
| --- | --- |
| `id` | `ProposalId` (UUIDv7) |
| `title`, `description` | Reviewer-facing. |
| `status` | `draft → pending → approved/rejected`, `approved → merged`. |
| `proposed_events` | Serialized envelopes targeting memory streams. They do not touch target streams until merge. |
| `review_note` | Free text from the reviewer. |

Merge re-validates proposed events against the *current* target streams; a moved target is
a conflict (`StaleVersionError` → HTTP 409), never a silent overwrite.

## Value objects

`MemoryId`, `ProposalId` (NewType over UUID), `Slug`, `MemoryType`, `LinkRelation`,
`Salience` — all frozen, all validated at construction (`ValidationError`).
`Provenance` (kernel): `actor` + optional `session_id`/`detail`; every event carries one.

## Ports (what the domain needs from the world)

Defined in `ports.py`, implemented by adapters, wired in app composition roots:

| Port | Side | Canonical adapter |
| --- | --- | --- |
| `MemoryRepository`, `ProposalRepository` | write | engram-storage-sqlite |
| `MemoryQuery` | read | engram-storage-sqlite |
| `SearchIndex` (`supports_vectors` capability flag) | read | engram-storage-sqlite (FTS later, vec later) |
| `EmbeddingProvider` | — | none (interface reserved; roadmap phase 6) |
| `MarkdownSync`, `VersionControl` | export | engram-export-git |
| `Clock` | ambient | app-provided |
| `EventStore`, `EventBus`, `Projection` | kernel | engram-storage-sqlite / in-process bus |
