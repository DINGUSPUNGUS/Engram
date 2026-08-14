"""M9 upgrade audit, ADR-0026: the full old-state -> upgrade -> rebuild ->
equivalent-state story, through the real CLI binary.

Simulates a genuinely older engram install: an event log written while the
database was still on migration 0004 (one behind head, which added
``memories.access_count``/``last_accessed_at`` in 0005). The event itself is
appended through the real event store, not hand-typed SQL -- ``events`` is one
table, created once in migration 0001 and never altered since, so this is
exactly what a real historical event log looks like regardless of how far
the *projection* schema has since moved on.
"""

from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from typer.testing import CliRunner

from engram_cli.main import app
from engram_core.application.commands.memory_commands import MemoryCommandService
from engram_core.application.dto import CreateMemoryInput
from engram_core.domain.kinds import build_kind_registry
from engram_core.domain.values import MemoryKind
from engram_events import InProcessEventBus, Provenance, SystemClock
from engram_storage_sqlite.event_store import SqliteEventStore, create_sqlite_engine
from engram_storage_sqlite.repositories import SqliteMemoryRepository

runner = CliRunner()

_PACKAGE_ROOT = Path(__file__).resolve().parents[3] / "libs" / "engram-storage-sqlite"
_STALE_REVISION = "0004"

USER = Provenance(actor="user", detail="test")


def _write_stale_schema_space_with_one_memory(db_path: Path) -> str:
    """Build a database stamped at ``_STALE_REVISION`` (not head) with one
    real ``MemoryCreated`` event already in its log -- standing in for a
    space created by a genuinely older engram binary."""
    from engram_core.domain.events import build_registry

    config = Config(str(_PACKAGE_ROOT / "alembic.ini"))
    config.set_main_option("sqlalchemy.url", f"sqlite:///{db_path}")
    command.upgrade(config, _STALE_REVISION)

    engine = create_sqlite_engine(f"sqlite:///{db_path}")
    store = SqliteEventStore(engine, build_registry())
    kinds = build_kind_registry()
    repository = SqliteMemoryRepository(store, kinds)
    # No projection subscriber: the 0004 schema's `memories` table can't take
    # 0005's columns anyway -- exactly the state a real pre-upgrade space
    # would be in (log ahead of / independent from the projection schema).
    commands = MemoryCommandService(repository, InProcessEventBus(), SystemClock(), kinds, store)
    memory_id = commands.create_memory(
        CreateMemoryInput(
            kind=MemoryKind.FACT,
            title="pre-upgrade memory",
            content="",
            attributes={"statement": "written before the schema was upgraded"},
        ),
        USER,
    )
    engine.dispose()
    return str(memory_id)


@pytest.fixture
def stale_space(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, str]:
    db_path = tmp_path / "engram.db"
    monkeypatch.setenv("ENGRAM_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("ENGRAM_DB_PATH", str(db_path))
    memory_id = _write_stale_schema_space_with_one_memory(db_path)
    return db_path, memory_id


@pytest.mark.integration
def test_commands_fail_fast_with_actionable_guidance_on_a_stale_schema(
    stale_space: tuple[Path, str],
) -> None:
    result = runner.invoke(app, ["list"])

    assert result.exit_code == 1, result.output
    assert "engram init" in result.output
    # The old failure mode this replaces: a raw SQLAlchemy/sqlite3 dump with
    # no guidance at all. Neither should ever reach the user again.
    assert "OperationalError" not in result.output
    assert "Traceback" not in result.output


@pytest.mark.integration
def test_old_state_upgrade_rebuild_yields_equivalent_state(
    stale_space: tuple[Path, str],
) -> None:
    db_path, memory_id = stale_space

    # Old state: the event is durably logged, but this build refuses to
    # project a stale schema (previous test) -- confirm the log itself
    # already holds it, untouched, before any upgrade happens.
    import sqlite3

    with sqlite3.connect(db_path) as conn:
        (count,) = conn.execute("SELECT COUNT(*) FROM events").fetchone()
    assert count == 1

    # Upgrade: the sanctioned recovery `engram init` documents.
    result = runner.invoke(app, ["init"])
    assert result.exit_code == 0, result.output

    # Rebuild: re-project the (unchanged) log into the now-current schema.
    result = runner.invoke(app, ["rebuild"])
    assert result.exit_code == 0, result.output
    assert "1 events" in result.output

    # Equivalent state: the memory written before the upgrade is visible,
    # correct, and the space reports healthy -- not drifted, not degraded.
    result = runner.invoke(app, ["show", memory_id])
    assert result.exit_code == 0, result.output
    assert "pre-upgrade memory" in result.output
    assert "written before the schema was upgraded" in result.output

    result = runner.invoke(app, ["status"])
    assert result.exit_code == 0, result.output
    assert "events: 1" in result.output
    assert "DRIFTED" not in result.output

    result = runner.invoke(app, ["status", "--verify"])
    assert result.exit_code == 0, result.output
    assert "verified" in result.output
    assert "MISMATCH" not in result.output
