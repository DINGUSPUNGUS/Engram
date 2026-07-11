"""initial schema: append-only event log + rebuildable projections

Carries the Phase 0.5 memory model (docs/memory-model.md): twelve-kind memories
with JSON attributes and the justification spine, plus the evidence table.
Revised in place pre-release — no deployment predates it.

Revision ID: 0001
Revises:
Create Date: 2026-07-10 (revised 2026-07-11)
"""

from alembic import op
import sqlalchemy as sa

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # -- system of record ---------------------------------------------------
    op.create_table(
        "events",
        sa.Column("global_seq", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("event_id", sa.String(length=36), nullable=False, unique=True),
        sa.Column("stream_id", sa.String(length=36), nullable=False),
        sa.Column("stream_seq", sa.Integer(), nullable=False),
        sa.Column("event_type", sa.String(length=100), nullable=False),
        sa.Column("schema_version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("payload", sa.Text(), nullable=False),
        sa.Column("occurred_at", sa.DateTime(), nullable=False),
        sa.Column("provenance", sa.Text(), nullable=False),
        sa.UniqueConstraint("stream_id", "stream_seq", name="uq_events_stream_position"),
    )
    op.create_index("ix_events_stream_id", "events", ["stream_id"])
    op.create_index("ix_events_event_type", "events", ["event_type"])

    # The log is append-only at the engine level, not just by convention.
    op.execute(
        "CREATE TRIGGER events_append_only_update BEFORE UPDATE ON events "
        "BEGIN SELECT RAISE(ABORT, 'events is append-only'); END"
    )
    op.execute(
        "CREATE TRIGGER events_append_only_delete BEFORE DELETE ON events "
        "BEGIN SELECT RAISE(ABORT, 'events is append-only'); END"
    )

    # -- projections (rebuildable) -------------------------------------------
    op.create_table(
        "memories",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("kind", sa.String(length=20), nullable=False),
        sa.Column("slug", sa.String(length=80), nullable=False, unique=True),
        sa.Column("title", sa.String(length=500), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("attributes", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("attributes_schema_version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("confidence", sa.Float(), nullable=False, server_default="0.6"),
        sa.Column("last_confirmed_at", sa.DateTime(), nullable=True),
        sa.Column(
            "lifetime_policy", sa.String(length=20), nullable=False, server_default="standard"
        ),
        sa.Column("lifetime_until", sa.DateTime(), nullable=True),
        sa.Column("visibility", sa.String(length=20), nullable=False, server_default="shared"),
        sa.Column("allowed_actors", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("pinned", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("user_weight", sa.Float(), nullable=True),
        sa.Column("archived", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
    )
    op.create_index("ix_memories_kind", "memories", ["kind"])
    op.create_index("ix_memories_archived", "memories", ["archived"])
    op.create_index("ix_memories_visibility", "memories", ["visibility"])
    op.create_index("ix_memories_lifetime_policy", "memories", ["lifetime_policy"])
    op.create_index("ix_memories_pinned", "memories", ["pinned"])
    # Kind-specific expression indexes on hot attributes (memory-model.md §11).
    op.execute(
        "CREATE INDEX ix_memories_attr_status ON memories "
        "(json_extract(attributes, '$.status')) WHERE kind IN ('project', 'goal')"
    )
    op.execute(
        "CREATE INDEX ix_memories_attr_name ON memories "
        "(json_extract(attributes, '$.name')) "
        "WHERE kind IN ('person', 'organization', 'project', 'skill', 'location')"
    )

    op.create_table(
        "evidence",
        sa.Column(
            "memory_id",
            sa.String(length=36),
            sa.ForeignKey("memories.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("seq", sa.Integer(), primary_key=True),
        sa.Column("evidence_type", sa.String(length=20), nullable=False),
        sa.Column("value", sa.Text(), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("added_at", sa.DateTime(), nullable=False),
        sa.Column("actor", sa.String(length=100), nullable=False),
    )

    op.create_table(
        "memory_tags",
        sa.Column(
            "memory_id",
            sa.String(length=36),
            sa.ForeignKey("memories.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("tag", sa.String(length=100), primary_key=True),
    )
    op.create_index("ix_memory_tags_tag", "memory_tags", ["tag"])

    op.create_table(
        "links",
        sa.Column(
            "source_id",
            sa.String(length=36),
            sa.ForeignKey("memories.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("target_id", sa.String(length=36), primary_key=True),
        sa.Column("relation", sa.String(length=30), primary_key=True),
    )
    op.create_index("ix_links_target_id", "links", ["target_id"])

    op.create_table(
        "projection_checkpoints",
        sa.Column("projection_name", sa.String(length=100), primary_key=True),
        sa.Column("last_global_seq", sa.Integer(), nullable=False, server_default="0"),
    )

    op.create_table(
        "index_meta",
        sa.Column("key", sa.String(length=100), primary_key=True),
        sa.Column("value", sa.Text(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("index_meta")
    op.drop_table("projection_checkpoints")
    op.drop_table("links")
    op.drop_table("memory_tags")
    op.drop_table("evidence")
    op.drop_table("memories")
    op.execute("DROP TRIGGER IF EXISTS events_append_only_update")
    op.execute("DROP TRIGGER IF EXISTS events_append_only_delete")
    op.drop_table("events")
