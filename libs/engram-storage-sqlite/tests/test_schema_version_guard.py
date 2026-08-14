"""M9 upgrade audit (ADR-0026): opening an engram space whose SQLite schema
predates this build's Alembic migrations must fail fast with guidance, not
run a write against columns that don't exist yet.

``require_current_schema`` is the guard; these tests exercise it directly,
independent of the CLI (see apps/cli/tests/test_cli_schema_upgrade_e2e.py for
the full old-state -> upgrade -> rebuild -> equivalent-state proof through
the real binary).
"""

from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy.engine import Engine

from engram_core.domain.errors import StorageError
from engram_storage_sqlite.event_store import create_sqlite_engine
from engram_storage_sqlite.migrate import require_current_schema, schema_status, upgrade_to_head

_PACKAGE_ROOT = Path(__file__).resolve().parents[1]

# One revision behind head, on purpose -- 0005 is the newest migration as of
# this test; if a later migration lands, this still proves the same thing
# (some revision short of head), it just stops being *the* newest one behind.
_STALE_REVISION = "0004"


def _stale_db(tmp_path: Path) -> Path:
    db_path = tmp_path / "engram-test.db"
    config = Config(str(_PACKAGE_ROOT / "alembic.ini"))
    config.set_main_option("sqlalchemy.url", f"sqlite:///{db_path}")
    command.upgrade(config, _STALE_REVISION)
    return db_path


@pytest.mark.integration
def test_schema_status_reports_stale_database_as_not_up_to_date(tmp_path: Path) -> None:
    db_path = _stale_db(tmp_path)
    engine = create_sqlite_engine(f"sqlite:///{db_path}")

    status = schema_status(engine)

    assert status.current == _STALE_REVISION
    assert status.head is not None
    assert status.head != _STALE_REVISION
    assert not status.up_to_date


@pytest.mark.integration
def test_schema_status_reports_freshly_migrated_database_as_up_to_date(tmp_path: Path) -> None:
    db_path = tmp_path / "engram-test.db"
    upgrade_to_head(db_path)
    engine = create_sqlite_engine(f"sqlite:///{db_path}")

    status = schema_status(engine)

    assert status.up_to_date
    assert status.current == status.head


@pytest.mark.integration
def test_require_current_schema_raises_actionable_error_on_stale_database(
    tmp_path: Path,
) -> None:
    db_path = _stale_db(tmp_path)
    engine = create_sqlite_engine(f"sqlite:///{db_path}")

    with pytest.raises(StorageError, match="engram init") as excinfo:
        require_current_schema(db_path, engine)
    # The whole point: a user who has never heard of Alembic revisions still
    # gets told exactly what command fixes this, not a raw SQL dump.
    assert "engram rebuild" in str(excinfo.value)


@pytest.mark.integration
def test_require_current_schema_is_silent_on_a_current_database(
    tmp_path: Path, engine: Engine, db_path: Path
) -> None:
    require_current_schema(db_path, engine)  # must not raise
