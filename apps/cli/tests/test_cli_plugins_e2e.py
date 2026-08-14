"""M8 end-to-end through the real binary surface: `engram plugins run` opens a
proposal (never writes memory directly), a human reviews/approves/merges it
exactly like any other proposal, and replay reproduces the result — proving
the plugin architecture (ADR-0024) through the actual CLI, not just the
library's own test suite."""

import re
import sys
from pathlib import Path

import pytest
from typer.testing import CliRunner

from engram_cli.main import app

runner = CliRunner()

_PLUGIN_MODULE_PREFIXES = ("engram_plugins", "engram_cli.plugins")


def _simulate_plugins_package_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    """Simulate `engram-plugins` genuinely not being installed, without
    uninstalling it: evict every already-imported `engram_plugins`/
    `engram_cli.plugins` module from the cache (so a fresh import is actually
    attempted rather than served from ``sys.modules``), then poison
    ``engram_plugins`` itself — ``sys.modules[name] = None`` is the standard
    mechanism that makes the next ``import engram_plugins`` raise
    ``ModuleNotFoundError`` exactly as it would if the package were absent.
    ``monkeypatch`` restores the real cache entries afterward."""
    for name in [n for n in sys.modules if n.startswith(_PLUGIN_MODULE_PREFIXES)]:
        monkeypatch.delitem(sys.modules, name, raising=False)
    monkeypatch.setitem(sys.modules, "engram_plugins", None)


def _extract(pattern: str, output: str) -> str:
    match = re.search(pattern, output)
    assert match, output
    return match.group(1)


@pytest.fixture
def space(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("ENGRAM_DATA_DIR", str(tmp_path / "engram"))
    monkeypatch.setenv("ENGRAM_DB_PATH", str(tmp_path / "engram" / "engram.db"))
    assert runner.invoke(app, ["init"]).exit_code == 0
    return tmp_path


@pytest.mark.integration
def test_plugins_list_shows_the_reference_plugin_enabled(space: Path) -> None:
    result = runner.invoke(app, ["plugins", "list"])
    assert result.exit_code == 0, result.output
    assert "dev.engram.reference-url-evidence@1.0.0" in result.output
    assert "enabled" in result.output
    assert "proposal_submit" in result.output


@pytest.mark.integration
def test_plugin_run_review_merge_replay_end_to_end(space: Path) -> None:
    add = runner.invoke(
        app,
        [
            "add",
            "fact",
            "engram repo",
            "--content",
            "See https://github.com/example/engram for the source.",
            "--attr",
            "statement=engram repo location",
        ],
    )
    assert add.exit_code == 0, add.output
    memory_id = _extract(r"id: ([0-9a-f-]{36})", add.output)

    result = runner.invoke(app, ["plugins", "run", "dev.engram.reference-url-evidence"])
    assert result.exit_code == 0, result.output
    proposal_id = _extract(r"opened proposal ([0-9a-f-]{36})", result.output)

    # Nothing became memory yet — the plugin only proposed.
    show = runner.invoke(app, ["show", memory_id])
    assert "evidence" not in show.output.lower() or "uri" not in show.output.lower()

    detail = runner.invoke(app, ["proposals", "show", proposal_id])
    assert detail.exit_code == 0, detail.output
    assert "add_evidence" in detail.output

    # A plugin's own proposal cannot be merged before a human approves it.
    premature = runner.invoke(app, ["proposals", "merge", proposal_id])
    assert premature.exit_code != 0

    assert runner.invoke(app, ["proposals", "approve", proposal_id, "-n", "ok"]).exit_code == 0
    merged = runner.invoke(app, ["proposals", "merge", proposal_id])
    assert merged.exit_code == 0, merged.output

    show = runner.invoke(app, ["show", memory_id])
    assert "https://github.com/example/engram" in show.output

    # Replay reproduces this without ever executing plugin code (ADR-0024 §9):
    # rebuild only replays the raw event log through the projections.
    rebuild = runner.invoke(app, ["rebuild"])
    assert rebuild.exit_code == 0, rebuild.output
    status = runner.invoke(app, ["status"])
    assert status.exit_code == 0 and "DRIFTED" not in status.output
    rebuilt = runner.invoke(app, ["show", memory_id])
    assert "https://github.com/example/engram" in rebuilt.output


@pytest.mark.integration
def test_plugins_list_fails_cleanly_when_package_missing(
    space: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _simulate_plugins_package_missing(monkeypatch)

    result = runner.invoke(app, ["plugins", "list"])

    assert result.exit_code == 1
    # A controlled exit (SystemExit from typer.Exit), never the raw
    # ModuleNotFoundError propagating out uncaught.
    assert isinstance(result.exception, SystemExit), result.exception
    assert "engram-plugins" in result.output
    assert "not installed" in result.output
    assert "Traceback" not in result.output


@pytest.mark.integration
def test_plugins_run_fails_cleanly_when_package_missing(
    space: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _simulate_plugins_package_missing(monkeypatch)

    result = runner.invoke(app, ["plugins", "run", "dev.engram.reference-url-evidence"])

    assert result.exit_code == 1
    # A controlled exit (SystemExit from typer.Exit), never the raw
    # ModuleNotFoundError propagating out uncaught.
    assert isinstance(result.exception, SystemExit), result.exception
    assert "engram-plugins" in result.output
    assert "not installed" in result.output
    assert "Traceback" not in result.output


def test_missing_plugins_guard_does_not_swallow_unrelated_import_failures() -> None:
    """Unit-level proof that the guard is scoped to ``engram_plugins``
    specifically (not any ``ModuleNotFoundError`` that happens to surface
    while importing the plugin composition module) — the CLI's exact rule:
    'do not catch unrelated import/runtime failures as though the package
    were simply unavailable'."""
    from engram_cli.main import _is_missing_plugins_package

    assert _is_missing_plugins_package(ModuleNotFoundError("x", name="engram_plugins"))
    assert _is_missing_plugins_package(ModuleNotFoundError("x", name="engram_plugins.gateway"))
    assert not _is_missing_plugins_package(
        ModuleNotFoundError("x", name="totally_unrelated_dependency")
    )
    assert not _is_missing_plugins_package(ModuleNotFoundError("x", name="engram_core"))
    # A module with no name that merely resembles the prefix must not match either.
    assert not _is_missing_plugins_package(
        ModuleNotFoundError("x", name="engram_plugins_lookalike")
    )
