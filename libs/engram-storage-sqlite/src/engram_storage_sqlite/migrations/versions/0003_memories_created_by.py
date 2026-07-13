"""memories.created_by: the creation event's provenance actor (M3)

The markdown export's frontmatter carries per-memory provenance; only the
``MemoryCreated`` envelope knows it, so the state projection captures it.
Existing rows get the default and are corrected by ``engram rebuild``.

Revision ID: 0003
Revises: 0002
Create Date: 2026-07-12
"""

import sqlalchemy as sa
from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "memories",
        sa.Column("created_by", sa.String(length=100), nullable=False, server_default="user"),
    )


def downgrade() -> None:
    op.drop_column("memories", "created_by")
