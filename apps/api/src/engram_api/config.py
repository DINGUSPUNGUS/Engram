"""Application settings (pydantic-settings).

Configuration lives in apps, never in engram-core — core receives values via
constructors. Precedence (highest wins): explicit init kwargs > environment
variables > .env file > ~/.config/engram/config.toml > defaults.
"""

from pathlib import Path
from typing import Literal

from pydantic_settings import (
    BaseSettings,
    PydanticBaseSettingsSource,
    SettingsConfigDict,
    TomlConfigSettingsSource,
)

_USER_CONFIG_TOML = Path.home() / ".config" / "engram" / "config.toml"


class EngramSettings(BaseSettings):
    """All runtime configuration for the API process."""

    model_config = SettingsConfigDict(
        env_prefix="ENGRAM_",
        env_file=".env",
        extra="ignore",
        toml_file=_USER_CONFIG_TOML,
    )

    data_dir: Path = Path.home() / ".engram"
    db_path: Path | None = None
    export_repo: Path | None = None
    api_host: str = "127.0.0.1"
    api_port: int = 8000
    log_level: str = "INFO"
    log_format: Literal["console", "json"] = "console"
    env: Literal["development", "production", "test"] = "development"

    @property
    def resolved_db_path(self) -> Path:
        return self.db_path if self.db_path is not None else self.data_dir / "engram.db"

    @property
    def resolved_export_repo(self) -> Path:
        return self.export_repo if self.export_repo is not None else self.data_dir / "memory"

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        return (
            init_settings,
            env_settings,
            dotenv_settings,
            TomlConfigSettingsSource(settings_cls),
            file_secret_settings,
        )
