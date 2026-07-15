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
