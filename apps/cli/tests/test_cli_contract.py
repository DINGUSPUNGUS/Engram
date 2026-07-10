"""CLI contract: help works, stubs fail loudly and honestly (exit 1, message)."""

import pytest
from typer.testing import CliRunner

from engram_cli.main import app

runner = CliRunner()


@pytest.mark.unit
def test_help_lists_all_commands() -> None:
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    for command in ("init", "status", "rebuild", "export"):
        assert command in result.output


@pytest.mark.unit
@pytest.mark.parametrize("command", ["init", "status", "rebuild", "export"])
def test_stub_commands_exit_1_with_message(command: str) -> None:
    result = runner.invoke(app, [command])
    assert result.exit_code == 1
    assert "architecture phase" in result.output
