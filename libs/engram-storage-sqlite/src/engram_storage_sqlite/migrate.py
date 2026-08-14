"""Programmatic Alembic migration — what ``engram init`` runs — and the
schema-version guard every other command relies on to fail fast instead of
running against a stale DDL schema (M9 upgrade audit, ADR-0026).

Locates the packaged migration scripts via importlib.resources, so it works from
an installed wheel as well as the workspace checkout.
"""

from dataclasses import dataclass
from importlib import resources
from pathlib import Path

from alembic import command
from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy.engine import Engine

from engram_core.domain.errors import StorageError


def _alembic_config(db_path: Path | None = None) -> Config:
    migrations = resources.files("engram_storage_sqlite") / "migrations"
    config = Config()
    config.set_main_option("script_location", str(migrations))
    if db_path is not None:
        config.set_main_option("sqlalchemy.url", f"sqlite:///{db_path}")
    return config


def upgrade_to_head(db_path: Path) -> None:
    """Create/upgrade the engram database schema at ``db_path``. Idempotent —
    Alembic applies only the migrations a given database hasn't seen yet, so
    re-running this against an already-current database is a no-op."""
    config = _alembic_config(db_path)
    try:
        db_path.parent.mkdir(parents=True, exist_ok=True)
        command.upgrade(config, "head")
    except Exception as exc:  # alembic raises broadly; translate at the boundary
        raise StorageError(f"migration failed for {db_path}: {exc}") from exc


@dataclass(frozen=True, slots=True)
class SchemaStatus:
    """The database's applied Alembic revision vs. this build's migration head."""

    current: str | None
    head: str | None

    @property
    def up_to_date(self) -> bool:
        return self.current == self.head


def schema_status(engine: Engine) -> SchemaStatus:
    """Read-only comparison — runs no migration, changes nothing."""
    head = ScriptDirectory.from_config(_alembic_config()).get_current_head()
    with engine.connect() as connection:
        current = MigrationContext.configure(connection).get_current_revision()
    return SchemaStatus(current=current, head=head)


def require_current_schema(db_path: Path, engine: Engine) -> None:
    """Fail fast, before any command touches the database, if its schema
    predates this build's migrations.

    Why this matters: the event log itself is one append-only table, created
    once in migration 0001 and never altered since — it is always readable
    regardless of schema version, which is why events keep appending even
    against a stale schema (confirmed by
    ``test_open_old_schema_space_with_newer_binary.py``). What breaks is the
    *projection* layer: this build's ORM models assume columns later
    migrations added (e.g. 0005's ``memories.access_count``), and a stale
    schema doesn't have them yet. Without this guard, the first write's
    projection step fails with a raw ``sqlite3.OperationalError`` naming a
    missing column and no indication of why — technically safe (the existing
    per-projection transaction still leaves no phantom checkpoint, P1 §2) but
    useless to a user who has no reason to know "no such column" means
    "run a migration."

    The sanctioned recovery is exactly what ``engram init``'s own docstring
    already promises ("create *or upgrade*"): re-run it — idempotent, reapplies
    only pending migrations — then ``engram rebuild`` to re-project the
    (unchanged, undamaged) event log into the now-current schema.
    """
    status = schema_status(engine)
    if not status.up_to_date:
        raise StorageError(
            f"{db_path} is at schema {status.current!r}, but this build of engram"
            f" expects {status.head!r}. Run `engram init` to upgrade it in place"
            " (your event history is untouched by this), then `engram rebuild`"
            " to re-project it."
        )
