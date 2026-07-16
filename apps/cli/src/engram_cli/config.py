"""CLI settings (pydantic-settings). Config lives in apps, never in core."""

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class CliSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="ENGRAM_", env_file=".env", extra="ignore")

    data_dir: Path = Path.home() / ".engram"
    db_path: Path | None = None
    export_repo: Path | None = None

    # LLM provider selection (ADR-0012): ollama is the local-first default;
    # "fake" replays canned responses for reproducible demos/tests/CI.
    llm_provider: str = "ollama"
    llm_model: str = "llama3.2:1b"
    llm_base_url: str = "http://127.0.0.1:11434"
    llm_seed: int = 42
    llm_timeout_seconds: float = 120.0
    llm_fake_responses: Path | None = None

    @property
    def resolved_db_path(self) -> Path:
        return self.db_path if self.db_path is not None else self.data_dir / "engram.db"

    @property
    def resolved_export_repo(self) -> Path:
        return self.export_repo if self.export_repo is not None else self.data_dir / "memory"
