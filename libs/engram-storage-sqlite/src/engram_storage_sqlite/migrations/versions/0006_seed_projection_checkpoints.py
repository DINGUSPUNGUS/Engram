"""seed projection_checkpoints rows (PRE-M10 GATE, concurrency P2)

Each projection's ``_checkpoint_row`` used check-then-insert (SELECT the row;
if none, construct one and add it) to lazily create its ``projection_checkpoints``
row on the very first ``apply()`` call. Under high write concurrency (8+) on a
freshly-``init``'d space — before *any* projection had ever applied a single
event yet — two writers' first ``apply()`` calls could both see no row, both
attempt to INSERT the same primary key, and the loser crash with a raw
``UNIQUE constraint failed``. Its event stayed durably logged (the log is
unaffected), but that one event's projection application was then permanently
skipped by the normal per-event apply path, silently invisible to
``list``/``search``/``get`` until the next ``engram rebuild``.

Seeding all three rows here, once, at migration time — the same point every
other structural guarantee about a freshly-created space is established —
removes the race entirely for any space migrated by this build forward: the
row already exists before a single event can ever be appended, so the
check-then-insert's "no row yet" branch is simply never reached again.
``INSERT OR IGNORE`` makes this safe to run against an already-populated
database too (the overwhelmingly common case: almost every real space already
has these rows from ordinary single-writer use before ever hitting the race).

Revision ID: 0006
Revises: 0005
Create Date: 2026-08-14
"""

import sqlalchemy as sa
from alembic import op

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None

_PROJECTION_NAMES = ("state", "search", "proposals")


def upgrade() -> None:
    connection = op.get_bind()
    for name in _PROJECTION_NAMES:
        connection.execute(
            sa.text(
                "INSERT OR IGNORE INTO projection_checkpoints"
                " (projection_name, last_global_seq) VALUES (:name, 0)"
            ),
            {"name": name},
        )


def downgrade() -> None:
    connection = op.get_bind()
    for name in _PROJECTION_NAMES:
        connection.execute(
            sa.text(
                "DELETE FROM projection_checkpoints"
                " WHERE projection_name = :name AND last_global_seq = 0"
            ),
            {"name": name},
        )
