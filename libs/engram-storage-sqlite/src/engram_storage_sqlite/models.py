"""Initial schema — the one intentionally implemented piece of the skeleton.

Two categories of table, with very different contracts:

- ``events`` is the **system of record**: append-only (SQLite triggers in the
  initial migration reject UPDATE/DELETE), totally ordered by ``global_seq``,
  per-stream ordered by (``stream_id``, ``stream_seq``).
- Everything else is a **projection**: disposable, rebuilt by replaying the log
  (``engram rebuild``). Dropping a projection table loses nothing.

UUIDs are stored as canonical lowercase strings; timestamps as UTC ISO-8601 —
SQLite-friendly and greppable. FTS5 / sqlite-vec virtual tables are deliberately
absent; their reserved names are documented in ADR-0001.
"""

from datetime import datetime

from sqlmodel import Field, SQLModel, UniqueConstraint

# ---------------------------------------------------------------------------
# System of record
# ---------------------------------------------------------------------------


class EventRecord(SQLModel, table=True):
    """One appended event envelope. Append-only, forever."""

    __tablename__ = "events"
    __table_args__ = (
        UniqueConstraint("stream_id", "stream_seq", name="uq_events_stream_position"),
    )

    global_seq: int | None = Field(default=None, primary_key=True)
    event_id: str = Field(unique=True)
    stream_id: str = Field(index=True)
    stream_seq: int
    event_type: str = Field(index=True)
    schema_version: int = 1
    payload: str = Field(description="JSON-encoded payload dataclass")
    occurred_at: datetime
    provenance: str = Field(description="JSON-encoded Provenance")


# ---------------------------------------------------------------------------
# Projections (rebuildable)
# ---------------------------------------------------------------------------


class MemoryRecord(SQLModel, table=True):
    """Current state of one memory. Deleted memories have no row here —
    their history lives on in ``events``."""

    __tablename__ = "memories"

    id: str = Field(primary_key=True)
    slug: str = Field(unique=True)
    memory_type: str = Field(index=True)
    title: str
    content: str
    archived: bool = Field(default=False, index=True)
    created_at: datetime
    updated_at: datetime
    version: int = Field(description="Last applied stream_seq; optimistic concurrency token")


class MemoryTagRecord(SQLModel, table=True):
    """Tag attachment (m:n). Tag names are free-form, normalized lowercase."""

    __tablename__ = "memory_tags"

    memory_id: str = Field(primary_key=True, foreign_key="memories.id")
    tag: str = Field(primary_key=True, index=True)


class LinkRecord(SQLModel, table=True):
    """Materialized graph edge between memories."""

    __tablename__ = "links"

    source_id: str = Field(primary_key=True, foreign_key="memories.id")
    target_id: str = Field(primary_key=True, foreign_key="memories.id")
    relation: str = Field(primary_key=True)


class ProjectionCheckpointRecord(SQLModel, table=True):
    """How far each projection has folded the log."""

    __tablename__ = "projection_checkpoints"

    projection_name: str = Field(primary_key=True)
    last_global_seq: int = 0


class IndexMetaRecord(SQLModel, table=True):
    """Store-level metadata (schema markers, capability flags)."""

    __tablename__ = "index_meta"

    key: str = Field(primary_key=True)
    value: str
