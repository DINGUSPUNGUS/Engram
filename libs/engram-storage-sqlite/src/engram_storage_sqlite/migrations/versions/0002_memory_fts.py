"""memory_fts: the FTS5 full-text projection table (M2, ADR-0016)

A projection like any other: disposable, rebuilt by replay. A plain (not
contentless) FTS5 table so the search projection can UPDATE/DELETE rows and
stay self-contained — it never reads other projections' tables.

Revision ID: 0002
Revises: 0001
Create Date: 2026-07-12
"""

from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "CREATE VIRTUAL TABLE memory_fts USING fts5("
        "memory_id UNINDEXED, title, content, tags, "
        "tokenize='porter unicode61')"
    )


def downgrade() -> None:
    op.execute("DROP TABLE memory_fts")
