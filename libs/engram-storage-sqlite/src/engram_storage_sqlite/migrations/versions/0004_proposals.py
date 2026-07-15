"""proposals: the review-queue projection (M4, ADR-0018)

A projection like any other: disposable, rebuilt by replay. Drafts are not
duplicated here — inspection folds the proposal's own stream; this table serves
listings and status filters.

Revision ID: 0004
Revises: 0003
Create Date: 2026-07-14
"""

import sqlalchemy as sa
from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "proposals",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("title", sa.String(length=500), nullable=False),
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="pending"),
        sa.Column("draft_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("review_note", sa.Text(), nullable=True),
        sa.Column("opened_by", sa.String(length=100), nullable=False, server_default="user"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
    )
    op.create_index("ix_proposals_status", "proposals", ["status"])


def downgrade() -> None:
    op.drop_table("proposals")
