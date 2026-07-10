# ADR-0003: Identity is an immutable UUIDv7; slugs and filenames are projections

- **Status**: Accepted
- **Date**: 2026-07-10

## Context

Memories are simultaneously database rows, event streams, markdown files, graph nodes, and
API resources. Filenames change (renames), slugs change (better titles), content changes
(edits). If any mutable attribute is used as identity, every rename is a distributed
consistency problem across links, streams, and the export repo.

## Decision

- `MemoryId` (and `ProposalId`) is a **UUIDv7**, minted at creation, never changed.
  UUIDv7 is time-ordered, which keeps SQLite indexes append-friendly and makes ids
  roughly sortable by creation time for free.
- The event stream id *is* the memory id. Links point at ids. API paths use ids.
- `slug` is a mutable, validated, human-friendly handle (`[a-z0-9-]`, ≤ 80).
- The export filename derives from type + slug; the frontmatter always carries the id;
  the export manifest maps id ↔ path. A rename is just events plus a file move in the
  next export commit.
- **Rule: nothing in the system may address a memory by filename or slug** — resolution
  goes through the id, always.

## Consequences

- Renames, merges, and moves are cheap and safe. ✔
- Every markdown file needs frontmatter with its id (acceptable; frontmatter carries
  type/tags/links anyway).
- Python 3.13 lacks stdlib `uuid7`; the kernel uses the `uuid6` package until stdlib
  support arrives (3.14+), behind `engram_events.new_uuid7()` so the swap is one line.
