"""M9 performance pass: ``create_sqlite_engine`` sets the PRAGMAs it claims to
set. ``synchronous=NORMAL`` is the one that actually matters for performance
(measured: raw commit latency ~11-20ms at the default FULL vs. ~0.3ms at
NORMAL, in WAL mode, on this benchmark machine) -- this test exists so that
setting silently regressing (e.g. an engine-creation refactor that drops the
``connect`` listener) fails loudly instead of quietly paying the fsync tax
again with no test ever noticing.
"""

from pathlib import Path

import pytest

from engram_storage_sqlite.event_store import create_sqlite_engine


@pytest.mark.integration
def test_engine_uses_wal_and_normal_synchronous(tmp_path: Path) -> None:
    engine = create_sqlite_engine(f"sqlite:///{tmp_path / 'pragma-test.db'}")
    with engine.connect() as connection:
        raw = connection.connection.driver_connection
        assert raw is not None
        journal_mode = raw.execute("PRAGMA journal_mode").fetchone()[0]
        synchronous = raw.execute("PRAGMA synchronous").fetchone()[0]
        foreign_keys = raw.execute("PRAGMA foreign_keys").fetchone()[0]

    assert journal_mode.lower() == "wal"
    # SQLite reports synchronous as an integer: OFF=0, NORMAL=1, FULL=2, EXTRA=3.
    assert synchronous == 1, f"expected NORMAL (1), got {synchronous}"
    assert foreign_keys == 1
    engine.dispose()
