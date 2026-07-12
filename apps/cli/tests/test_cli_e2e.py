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


@pytest.mark.integration
def test_query_engine_status_and_time_travel(space: Path) -> None:
    """M2 end to end: the query language, drift detection, and time travel."""
    assert runner.invoke(app, ["init"]).exit_code == 0

    result = runner.invoke(app, ["add", "fact", "User prefers dark mode", "-t", "ui"])
    fact_id = re.search(r"id: ([0-9a-f-]{36})", result.output).group(1)  # type: ignore[union-attr]
    runner.invoke(
        app,
        ["add", "project", "engram", "--attr", "name=engram", "--attr", "status=active"],
    )

    # -- status: healthy space, both projections at the head --------------------
    result = runner.invoke(app, ["status"])
    assert result.exit_code == 0, result.output
    assert "events: 2" in result.output
    assert "state" in result.output and "search" in result.output
    assert "DRIFTED" not in result.output

    # -- the query language: one string, many operators --------------------------
    result = runner.invoke(app, ["search", "dark"])
    assert result.exit_code == 0, result.output
    assert "User prefers dark mode" in result.output
    assert "engram" not in result.output

    result = runner.invoke(app, ["search", "kind:project status:active"])
    assert "engram" in result.output
    assert "dark mode" not in result.output

    result = runner.invoke(app, ["search", "confidence<0.7"])
    assert "no matches" in result.output  # CLI adds carry the 0.95 user prior

    result = runner.invoke(app, ["search", "kind:banana"])
    assert result.exit_code == 1
    assert "unknown kind" in result.output

    # -- time travel --------------------------------------------------------------
    result = runner.invoke(app, ["show", fact_id, "--version", "1"])
    assert result.exit_code == 0, result.output
    assert "time travel" in result.output
    assert "User prefers dark mode" in result.output

    result = runner.invoke(app, ["show", fact_id, "--at", "2000-01-01T00:00:00"])
    assert result.exit_code == 1
    assert "did not exist yet" in result.output

    # -- the M2 invariant, CLI face: rebuild restores the search projection ------
    result = runner.invoke(app, ["rebuild"])
    assert result.exit_code == 0, result.output
    result = runner.invoke(app, ["search", "dark"])
    assert "User prefers dark mode" in result.output
