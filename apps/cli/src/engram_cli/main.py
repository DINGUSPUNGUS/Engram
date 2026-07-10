"""The ``engram`` command. Architecture phase: commands are specified, not built.

Exit-code contract: 0 success · 1 expected failure (mapped EngramError) ·
2 usage error (Typer's default) · 70 unexpected internal error.
"""

import typer

from engram_cli import __version__

app = typer.Typer(
    name="engram",
    help="Git-native, event-sourced, user-owned memory for AI assistants.",
    no_args_is_help=True,
)

_NOT_IMPLEMENTED = (
    "engram is in its architecture phase — this command is specified but not built yet."
)


def _not_implemented() -> None:
    typer.secho(_NOT_IMPLEMENTED, fg=typer.colors.YELLOW, err=True)
    raise typer.Exit(code=1)


@app.callback(invoke_without_command=False)
def main(
    version: bool = typer.Option(False, "--version", help="Print version and exit"),
) -> None:
    if version:
        typer.echo(__version__)
        raise typer.Exit()


@app.command()
def init() -> None:
    """Create a new memory space: database, migrations, and export repository."""
    _not_implemented()


@app.command()
def status() -> None:
    """Show the space's health: event count, projection checkpoints, export drift."""
    _not_implemented()


@app.command()
def rebuild() -> None:
    """Replay the event log through every projection from the beginning."""
    _not_implemented()


@app.command()
def export() -> None:
    """Force a full markdown + NDJSON export to the git repository."""
    _not_implemented()


def run() -> None:
    """Entry point for the ``engram`` script."""
    app()
