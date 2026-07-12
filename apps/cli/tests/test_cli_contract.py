"""CLI contract: help lists everything; future-phase commands fail loudly."""

import pytest
from typer.testing import CliRunner

from engram_cli.main import app

runner = CliRunner()


@pytest.mark.unit
def test_help_lists_all_commands() -> None:
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    for command in ("init", "add", "list", "show", "rebuild", "status", "export"):
        assert command in result.output


@pytest.mark.unit
@pytest.mark.parametrize("command", ["status", "export"])
def test_future_phase_commands_exit_1_with_message(command: str) -> None:
    result = runner.invoke(app, [command])
    assert result.exit_code == 1
    assert "later roadmap phase" in result.output
