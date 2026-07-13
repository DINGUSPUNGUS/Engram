"""CLI contract: help lists every command surface."""

import pytest
from typer.testing import CliRunner

from engram_cli.main import app

runner = CliRunner()


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
