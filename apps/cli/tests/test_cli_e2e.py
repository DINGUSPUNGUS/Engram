"""End-to-end through the real binary surface: init → add → list → show → rebuild.

This is the milestone test: a memory is created, replayed, projected, and listed
via nothing but the CLI against a scratch database.
"""

import re
from pathlib import Path

import pytest
from typer.testing import CliRunner

from engram_cli.main import app

runner = CliRunner()


@pytest.fixture
def space(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("ENGRAM_DATA_DIR", str(tmp_path / "engram"))
    monkeypatch.setenv("ENGRAM_DB_PATH", str(tmp_path / "engram" / "engram.db"))
    return tmp_path / "engram"


@pytest.mark.integration
def test_first_memory_end_to_end(space: Path) -> None:
    # Commands before init fail with guidance, not tracebacks.
    result = runner.invoke(app, ["list"])
    assert result.exit_code == 1
    assert "engram init" in result.output

    result = runner.invoke(app, ["init"])
    assert result.exit_code == 0, result.output
    assert (space / "engram.db").exists()

    result = runner.invoke(app, ["add", "fact", "User prefers dark mode", "-t", "ui"])
    assert result.exit_code == 0, result.output
    match = re.search(r"id: ([0-9a-f-]{36})", result.output)
    assert match, result.output
    fact_id = match.group(1)

    result = runner.invoke(
        app,
        [
            "add",
            "project",
            "engram",
            "--attr",
            "name=engram",
            "--attr",
            "status=active",
            "-t",
            "oss",
            "-c",
            "the memory engine",
        ],
    )
    assert result.exit_code == 0, result.output

    # Kind-schema validation guards the front door.
    result = runner.invoke(app, ["add", "project", "half-baked", "--attr", "name=x"])
    assert result.exit_code == 1
    assert "status" in result.output

    result = runner.invoke(app, ["list"])
    assert result.exit_code == 0
    assert "User prefers dark mode" in result.output
    assert "engram" in result.output
    assert len([line for line in result.output.splitlines() if line.strip()]) == 2

    result = runner.invoke(app, ["list", "--kind", "project"])
    assert "engram" in result.output
    assert "dark mode" not in result.output

    result = runner.invoke(app, ["show", fact_id])
    assert result.exit_code == 0, result.output
    assert "timeline:" in result.output
    assert "MemoryCreated" in result.output
    assert "statement: User prefers dark mode" in result.output

    result = runner.invoke(app, ["rebuild"])
    assert result.exit_code == 0, result.output
    assert "2 events" in result.output

    # State survives the rebuild — the CLI-visible face of replay determinism.
    result = runner.invoke(app, ["list"])
    assert "User prefers dark mode" in result.output
    assert "engram" in result.output
