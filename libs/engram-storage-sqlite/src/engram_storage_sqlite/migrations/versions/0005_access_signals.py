"""access signals: MemoryAccessed history materialized on memories (M5, ADR-0009)

``access_count`` and ``last_accessed_at`` are stored *signals* folded from
``MemoryAccessed`` events; the retention score derived from them stays computed
at read time, never stored.

Revision ID: 0005
Revises: 0004
Create Date: 2026-07-15
"""

import sqlalchemy as sa
from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "memories",
        sa.Column("access_count", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column("memories", sa.Column("last_accessed_at", sa.DateTime(), nullable=True))


def downgrade() -> None:
    op.drop_column("memories", "last_accessed_at")
    op.drop_column("memories", "access_count")
