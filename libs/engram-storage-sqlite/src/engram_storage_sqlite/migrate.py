"""Programmatic Alembic migration — what ``engram init`` runs.

Locates the packaged migration scripts via importlib.resources, so it works from
an installed wheel as well as the workspace checkout.
"""

from importlib import resources
from pathlib import Path

from alembic import command
from alembic.config import Config

from engram_core.domain.errors import StorageError


def upgrade_to_head(db_path: Path) -> None:
    """Create/upgrade the engram database schema at ``db_path``."""
    migrations = resources.files("engram_storage_sqlite") / "migrations"
    config = Config()
    config.set_main_option("script_location", str(migrations))
    config.set_main_option("sqlalchemy.url", f"sqlite:///{db_path}")
    try:
        db_path.parent.mkdir(parents=True, exist_ok=True)
        command.upgrade(config, "head")
    except Exception as exc:  # alembic raises broadly; translate at the boundary
        raise StorageError(f"migration failed for {db_path}: {exc}") from exc
