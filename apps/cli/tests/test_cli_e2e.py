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


def _extract_id(output: str) -> str:
    match = re.search(r"id: ([0-9a-f-]{36})", output)
    assert match, output
    return match.group(1)


@pytest.fixture
def space(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("ENGRAM_DATA_DIR", str(tmp_path / "engram"))
    monkeypatch.setenv("ENGRAM_DB_PATH", str(tmp_path / "engram" / "engram.db"))
    monkeypatch.setenv("ENGRAM_EXPORT_REPO", str(tmp_path / "engram" / "memory"))
    for variable in ("GIT_AUTHOR_NAME", "GIT_COMMITTER_NAME"):
        monkeypatch.setenv(variable, "engram-test")
    for variable in ("GIT_AUTHOR_EMAIL", "GIT_COMMITTER_EMAIL"):
        monkeypatch.setenv(variable, "test@engram.local")
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


@pytest.mark.integration
def test_export_git_and_restore_round_trip(space: Path, tmp_path: Path) -> None:
    """M3 end to end: deterministic export, git versioning, lossless restore,
    and proposal-only import — all through the real binary surface."""
    assert runner.invoke(app, ["init"]).exit_code == 0

    result = runner.invoke(
        app, ["add", "project", "engram", "-a", "name=engram", "-a", "status=active", "-t", "oss"]
    )
    project_id = _extract_id(result.output)
    result = runner.invoke(app, ["add", "fact", "User prefers dark mode", "-t", "ui"])
    fact_id = _extract_id(result.output)
    assert runner.invoke(app, ["link", fact_id, project_id, "about"]).exit_code == 0

    # -- deterministic export ----------------------------------------------------
    repo = space / "memory"
    result = runner.invoke(app, ["export"])
    assert result.exit_code == 0, result.output
    assert (repo / "manifest.json").exists()
    assert (repo / "timeline" / "events.ndjson").exists()
    fact_files = list((repo / "memory" / "facts").glob("*.md"))
    assert len(fact_files) == 1
    document = fact_files[0].read_text(encoding="utf-8")
    assert f'id: "{fact_id}"' in document
    assert f'target: "{project_id}"' in document

    result = runner.invoke(app, ["export"])
    assert "unchanged" in result.output  # repeated export touches nothing

    # -- git consumes exports ------------------------------------------------------
    assert runner.invoke(app, ["git", "init"]).exit_code == 0
    result = runner.invoke(app, ["git", "commit"])
    assert result.exit_code == 0, result.output
    assert "committed" in result.output
    result = runner.invoke(app, ["git", "status"])
    assert "clean" in result.output

    # -- lossless restore into a brand-new space ----------------------------------
    reborn_db = tmp_path / "reborn" / "engram.db"
    with pytest.MonkeyPatch.context() as patch:
        patch.setenv("ENGRAM_DB_PATH", str(reborn_db))
        patch.setenv("ENGRAM_DATA_DIR", str(tmp_path / "reborn"))
        assert runner.invoke(app, ["init"]).exit_code == 0
        result = runner.invoke(app, ["import", str(repo), "--restore"])
        assert result.exit_code == 0, result.output
        assert "restored 3 events" in result.output
        result = runner.invoke(app, ["show", fact_id])
        assert result.exit_code == 0, result.output
        assert "User prefers dark mode" in result.output
        assert "MemoryLinked" in result.output

        # Restore refuses to run twice (the space is no longer empty).
        result = runner.invoke(app, ["import", str(repo), "--restore"])
        assert result.exit_code == 1
        assert "non-empty" in result.output

    # -- external knowledge only enters as a proposal ------------------------------
    note = tmp_path / "note.md"
    note.write_text(
        '---\nkind: "fact"\ntitle: "Imported note"\nattributes:\n  statement: "hello"\n---\nbody\n',
        encoding="utf-8",
    )
    result = runner.invoke(app, ["import", str(note)])
    assert result.exit_code == 0, result.output
    assert "opened proposal" in result.output
    result = runner.invoke(app, ["list"])
    assert "Imported note" not in result.output  # pending review, not memory


@pytest.mark.integration
def test_proposal_lifecycle_end_to_end(space: Path, tmp_path: Path) -> None:
    """M4 through the binary surface: external edit → reconciled proposal →
    inspect → approve → merge → undo → state restored, history intact."""
    assert runner.invoke(app, ["init"]).exit_code == 0
    result = runner.invoke(app, ["add", "fact", "User prefers dark mode", "-t", "ui"])
    fact_id = _extract_id(result.output)
    repo = space / "memory"
    assert runner.invoke(app, ["export"]).exit_code == 0

    # A human edits the exported file.
    fact_file = next((repo / "memory" / "facts").glob("*.md"))
    text = fact_file.read_text(encoding="utf-8").replace(
        'title: "User prefers dark mode"', 'title: "User prefers OLED dark"'
    )
    fact_file.write_text(text, encoding="utf-8")

    result = runner.invoke(app, ["import", str(repo / "memory")])
    assert result.exit_code == 0, result.output
    assert "1 edited" in result.output
    proposal_id = re.search(r"proposal ([0-9a-f-]{36})", result.output).group(1)  # type: ignore[union-attr]

    result = runner.invoke(app, ["proposals", "list"])
    assert "pending" in result.output
    result = runner.invoke(app, ["proposals", "show", proposal_id])
    assert result.exit_code == 0, result.output
    assert "edit_memory" in result.output
    assert "create_memory" not in result.output  # reconciled, never duplicated

    # Merge before approval is refused; the review pipeline is not optional.
    result = runner.invoke(app, ["proposals", "merge", proposal_id])
    assert result.exit_code == 1
    assert "only approved" in result.output

    assert runner.invoke(app, ["proposals", "approve", proposal_id, "-n", "lgtm"]).exit_code == 0
    result = runner.invoke(app, ["proposals", "merge", proposal_id])
    assert result.exit_code == 0, result.output
    result = runner.invoke(app, ["show", fact_id])
    assert "User prefers OLED dark" in result.output

    # Undo compensates; the timeline keeps the whole story.
    result = runner.invoke(app, ["proposals", "undo", proposal_id, "-n", "mistake"])
    assert result.exit_code == 0, result.output
    result = runner.invoke(app, ["show", fact_id])
    assert "User prefers dark mode" in result.output
    assert "MemoryEdited" in result.output  # both edits visible in the timeline

    # Replay determinism across the whole lifecycle.
    assert runner.invoke(app, ["rebuild"]).exit_code == 0
    result = runner.invoke(app, ["show", fact_id])
    assert "User prefers dark mode" in result.output
    result = runner.invoke(app, ["proposals", "list", "--status", "undone"])
    assert proposal_id in result.output
