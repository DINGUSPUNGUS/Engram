"""CLI contract: help lists every command surface."""

import sys

import pytest
from typer.testing import CliRunner

from engram_cli import __version__, main
from engram_cli.main import app

runner = CliRunner()


@pytest.mark.unit
def test_version_flag_prints_version_and_exits_zero() -> None:
    # Regression (M9 packaging audit): `--version` is a bare (non-eager)
    # option on a callback declared with invoke_without_command=False.
    # Click resolves whether a subcommand is required *before* it would
    # ever invoke that callback body, so a non-eager `--version` never ran
    # at all — `engram --version` failed with "Missing command" (exit 2)
    # instead of printing anything. Eager processing (is_eager=True +
    # callback=) is the only way an option on a group works without a
    # subcommand, matching how --help already behaves on this same app.
    result = runner.invoke(app, ["--version"])
    assert result.exit_code == 0, result.output
    assert result.output.strip() == __version__


@pytest.mark.unit
def test_help_lists_all_commands() -> None:
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    commands = (
        "init",
        "add",
        "list",
        "show",
        "search",
        "link",
        "rebuild",
        "status",
        "export",
        "import",
        "git",
    )
    for command in commands:
        assert command in result.output


@pytest.mark.unit
def test_git_subcommands_listed() -> None:
    result = runner.invoke(app, ["git", "--help"])
    assert result.exit_code == 0
    for command in ("init", "status", "commit"):
        assert command in result.output


@pytest.mark.unit
def test_unexpected_internal_error_exits_70_not_a_raw_traceback(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """PRE-M10 GATE finding: this module's docstring has promised exit code
    70 for "unexpected internal error" since M1, but ``_run`` only ever
    caught ``EngramError`` and ``run()``'s bare ``app()`` call let anything
    else propagate uncaught to Typer/Rich's default traceback renderer —
    a raw internal dump, exit code 1 (indistinguishable from an ordinary
    expected failure). ``CliRunner.invoke`` can't exercise this: it wraps
    Click's own invocation with its own exception handling, bypassing
    ``run()`` entirely — this calls ``run()`` itself, the real script entry
    point, the way ``python -m engram_cli`` / the installed console script
    actually do.
    """

    def _boom() -> None:
        raise RuntimeError("boom")

    monkeypatch.setattr(main, "_runtime", _boom)
    monkeypatch.setattr(sys, "argv", ["engram", "list"])

    with pytest.raises(SystemExit) as excinfo:
        main.run()

    assert excinfo.value.code == 70
    captured = capsys.readouterr()
    assert "unexpected internal error" in captured.err
    assert "boom" in captured.err
    assert "Traceback" not in captured.err
