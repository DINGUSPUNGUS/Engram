"""Integration test: the migration chain produces the contracted schema,
including the append-only enforcement on ``events``."""

import sqlite3
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config

_PACKAGE_ROOT = Path(__file__).resolve().parents[1]

EXPECTED_TABLES = {
    "events",
    "memories",
    "evidence",
    "memory_tags",
    "links",
    "projection_checkpoints",
    "index_meta",
    "memory_fts",  # M2; its five memory_fts_* shadow tables are FTS5 internals
    "proposals",  # M4: the review-queue projection
}


def _migrated_db(tmp_path: Path) -> Path:
    db_path = tmp_path / "engram-test.db"
    config = Config(str(_PACKAGE_ROOT / "alembic.ini"))
    config.set_main_option("sqlalchemy.url", f"sqlite:///{db_path}")
    command.upgrade(config, "head")
    return db_path


@pytest.mark.integration
def test_upgrade_head_creates_contracted_schema(tmp_path: Path) -> None:
    db_path = _migrated_db(tmp_path)
    with sqlite3.connect(db_path) as conn:
        tables = {
            row[0]
            for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
            if not row[0].startswith(("sqlite_", "alembic_", "memory_fts_"))
        }
        triggers = {
            row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'trigger'")
        }
    assert tables == EXPECTED_TABLES
    assert {"events_append_only_update", "events_append_only_delete"} <= triggers


@pytest.mark.integration
def test_events_table_rejects_update_and_delete(tmp_path: Path) -> None:
    db_path = _migrated_db(tmp_path)
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "INSERT INTO events (event_id, stream_id, stream_seq, event_type, payload,"
            " occurred_at, provenance) VALUES ('e1', 's1', 1, 'MemoryCreated', '{}',"
            " '2026-07-10T00:00:00', '{}')"
        )
        with pytest.raises(sqlite3.IntegrityError, match="append-only"):
            conn.execute("UPDATE events SET event_type = 'X' WHERE event_id = 'e1'")
        with pytest.raises(sqlite3.IntegrityError, match="append-only"):
            conn.execute("DELETE FROM events WHERE event_id = 'e1'")


@pytest.mark.integration
def test_stream_position_is_unique(tmp_path: Path) -> None:
    db_path = _migrated_db(tmp_path)
    insert = (
        "INSERT INTO events (event_id, stream_id, stream_seq, event_type, payload,"
        " occurred_at, provenance) VALUES (?, 's1', 1, 'MemoryCreated', '{}',"
        " '2026-07-10T00:00:00', '{}')"
    )
    with sqlite3.connect(db_path) as conn:
        conn.execute(insert, ("e1",))
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(insert, ("e2",))


@pytest.mark.integration
def test_projection_checkpoints_are_seeded_before_any_write(tmp_path: Path) -> None:
    """PRE-M10 GATE finding (concurrency P2): every projection's checkpoint
    row used to be created lazily, check-then-insert, on its own first
    ``apply()`` call — a real race under high write concurrency (8+) on a
    freshly-``init``'d space, confirmed reproducible: two writers' first
    ``apply()`` calls could both see no row and both attempt the INSERT, the
    loser crashing with a raw ``UNIQUE constraint failed`` while its own
    event stayed durably logged but permanently invisible to the projection.
    Migration 0006 seeds all three rows once, at migration time, so the
    check-then-insert race can never be reached again: this proves the rows
    already exist immediately after ``head``, before a single event has ever
    been appended or applied."""
    db_path = _migrated_db(tmp_path)
    with sqlite3.connect(db_path) as conn:
        rows = dict(
            conn.execute("SELECT projection_name, last_global_seq FROM projection_checkpoints")
        )
    assert rows == {"state": 0, "search": 0, "proposals": 0}


@pytest.mark.integration
def test_seed_migration_is_idempotent_on_a_database_that_already_has_progress(
    tmp_path: Path,
) -> None:
    """The seed must never regress real projection progress on a database
    that reaches 0006 with rows already past 0 (the ordinary case: almost
    every real space already has these rows from ordinary single-writer use
    well before ever hitting the concurrency race 0006 closes)."""
    db_path = tmp_path / "engram-test.db"
    config = Config(str(_PACKAGE_ROOT / "alembic.ini"))
    config.set_main_option("sqlalchemy.url", f"sqlite:///{db_path}")
    command.upgrade(config, "0005")
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "INSERT INTO projection_checkpoints (projection_name, last_global_seq)"
            " VALUES ('state', 42)"
        )
    command.upgrade(config, "head")
    with sqlite3.connect(db_path) as conn:
        rows = dict(
            conn.execute("SELECT projection_name, last_global_seq FROM projection_checkpoints")
        )
    assert rows["state"] == 42  # untouched, not reset to 0
    assert rows["search"] == 0 and rows["proposals"] == 0  # still seeded for the other two
