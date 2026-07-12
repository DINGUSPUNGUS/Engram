"""Shared fixtures: a migrated scratch database per test."""

from pathlib import Path

import pytest
from sqlalchemy.engine import Engine

from engram_storage_sqlite.event_store import create_sqlite_engine
from engram_storage_sqlite.migrate import upgrade_to_head


@pytest.fixture
def db_path(tmp_path: Path) -> Path:
    path = tmp_path / "engram-test.db"
    upgrade_to_head(path)
    return path


@pytest.fixture
def engine(db_path: Path) -> Engine:
    return create_sqlite_engine(f"sqlite:///{db_path}")
