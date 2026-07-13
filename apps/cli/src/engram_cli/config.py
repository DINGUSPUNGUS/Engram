"""CLI settings (pydantic-settings). Config lives in apps, never in core."""

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class CliSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="ENGRAM_", env_file=".env", extra="ignore")

    data_dir: Path = Path.home() / ".engram"
    db_path: Path | None = None
    export_repo: Path | None = None

    @property
    def resolved_db_path(self) -> Path:
        return self.db_path if self.db_path is not None else self.data_dir / "engram.db"

    @property
    def resolved_export_repo(self) -> Path:
        return self.export_repo if self.export_repo is not None else self.data_dir / "memory"
