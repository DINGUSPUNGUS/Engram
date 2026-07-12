"""Initial schema — the one intentionally implemented piece of the skeleton.

Two categories of table, with very different contracts:

- ``events`` is the **system of record**: append-only (SQLite triggers in the
  initial migration reject UPDATE/DELETE), totally ordered by ``global_seq``,
  per-stream ordered by (``stream_id``, ``stream_seq``).
- Everything else is a **projection**: disposable, rebuilt by replaying the log
  (``engram rebuild``). Dropping a projection table loses nothing.

The memory model of record is docs/memory-model.md: memories carry the twelve-kind
``kind`` discriminator, a JSON ``attributes`` payload (validated against the
KindRegistry *before* write — the DB stores only schema-valid data), and the
justification spine. Kind-specific querying uses expression indexes on
``json_extract(attributes, …)``; the query language's attribute operator rides them
(ADR-0016). Derived scores (effective confidence, retention) are NOT columns here —
they are computed at query time, per ADR-0009.

UUIDs are stored as canonical lowercase strings; timestamps as UTC ISO-8601.
The ``memory_fts`` FTS5 virtual table (migration 0002) is raw SQL, not a SQLModel —
it appears only in the search projection. ``memory_vectors`` stays reserved (M5).
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
    """Current state of one memory: kind, attributes, and the justification spine.
    Deleted memories have no row here — their history lives on in ``events``."""

    __tablename__ = "memories"

    id: str = Field(primary_key=True)
    kind: str = Field(index=True, description="One of the twelve MemoryKind values")
    slug: str = Field(unique=True)
    title: str
    content: str
    attributes: str = Field(description="JSON kind-schema payload (validated on write)")
    attributes_schema_version: int = 1
    confidence: float = Field(description="Stored confidence 0..1; decay is derived")
    last_confirmed_at: datetime | None = None
    lifetime_policy: str = Field(default="standard", index=True)
    lifetime_until: datetime | None = None
    visibility: str = Field(default="shared", index=True)
    allowed_actors: str = Field(default="[]", description="JSON list; RESTRICTED only")
    pinned: bool = Field(default=False, index=True)
    user_weight: float | None = None
    archived: bool = Field(default=False, index=True)
    created_at: datetime
    updated_at: datetime
    version: int = Field(description="Last applied stream_seq; optimistic concurrency token")


class EvidenceRecord(SQLModel, table=True):
    """Justification-spine evidence, append-only per memory."""

    __tablename__ = "evidence"

    memory_id: str = Field(primary_key=True, foreign_key="memories.id")
    seq: int = Field(primary_key=True, description="1-based per-memory order")
    evidence_type: str
    value: str
    note: str | None = None
    added_at: datetime
    actor: str


class MemoryTagRecord(SQLModel, table=True):
    """Tag attachment (m:n). Tag names are free-form, normalized lowercase."""

    __tablename__ = "memory_tags"

    memory_id: str = Field(primary_key=True, foreign_key="memories.id")
    tag: str = Field(primary_key=True, index=True)


class LinkRecord(SQLModel, table=True):
    """Materialized tier-1 graph edge (canonical direction only, ADR-0010)."""

    __tablename__ = "links"

    source_id: str = Field(primary_key=True, foreign_key="memories.id")
    target_id: str = Field(primary_key=True)
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
