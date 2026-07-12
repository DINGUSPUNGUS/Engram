"""The ``engram`` command. Phase 1: init, add, list, show, rebuild are real;
export lands with phase 4, status (drift details) with phase 2.

Exit-code contract: 0 success · 1 expected failure (mapped EngramError) ·
2 usage error (Typer's default) · 70 unexpected internal error.
"""

from collections.abc import Callable
from typing import Annotated
from uuid import UUID

import typer

from engram_cli import __version__
from engram_cli.config import CliSettings
from engram_cli.runtime import Runtime, build_runtime
from engram_core.application.dto import CreateMemoryInput, MemoryReadModel
from engram_core.domain.errors import EngramError, ValidationError
from engram_core.domain.values import MemoryId, MemoryKind
from engram_events import Provenance
from engram_storage_sqlite.migrate import upgrade_to_head

app = typer.Typer(
    name="engram",
    help="Git-native, event-sourced, user-owned memory for AI assistants.",
    no_args_is_help=True,
)

_NOT_IMPLEMENTED = (
    "this command is specified but lands with a later roadmap phase (docs/roadmap.md)."
)


def _fail(message: str) -> None:
    typer.secho(message, fg=typer.colors.RED, err=True)
    raise typer.Exit(code=1)


def _run[T](action: Callable[[], T]) -> T:
    """Run one command body under the exit-code contract."""
    try:
        return action()
    except EngramError as exc:
        typer.secho(str(exc), fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1) from exc


def _provenance() -> Provenance:
    """CLI invocations are the owning user acting directly."""
    return Provenance(actor="user", detail="engram-cli")


def _parse_attrs(pairs: list[str]) -> dict[str, object]:
    attributes: dict[str, object] = {}
    for pair in pairs:
        key, separator, value = pair.partition("=")
        if not separator or not key:
            raise ValidationError(f"--attr expects key=value, got: {pair!r}")
        attributes[key] = value
    return attributes


def _memory_line(memory: MemoryReadModel) -> str:
    flags = "".join(("A" if memory.archived else "", "S" if memory.stale else ""))
    suffix = f"  [{flags}]" if flags else ""
    return (
        f"{memory.id}  {memory.kind.value:<12} {memory.slug:<32}"
        f" c={memory.effective_confidence:.2f}  {memory.title}{suffix}"
    )


@app.callback(invoke_without_command=False)
def main(
    version: Annotated[bool, typer.Option("--version", help="Print version and exit")] = False,
) -> None:
    if version:
        typer.echo(__version__)
        raise typer.Exit()


@app.command()
def init() -> None:
    """Create (or upgrade) the memory space: data directory + database schema."""

    def action() -> None:
        settings = CliSettings()
        settings.data_dir.mkdir(parents=True, exist_ok=True)
        upgrade_to_head(settings.resolved_db_path)
        typer.secho(f"memory space ready: {settings.resolved_db_path}", fg=typer.colors.GREEN)

    _run(action)


@app.command()
def add(
    kind: Annotated[MemoryKind, typer.Argument(help="One of the twelve memory kinds")],
    title: Annotated[str, typer.Argument(help="Short human title")],
    content: Annotated[str, typer.Option("--content", "-c", help="Narrative markdown")] = "",
    slug: Annotated[str | None, typer.Option(help="Explicit slug (derived when omitted)")] = None,
    tag: Annotated[list[str], typer.Option("--tag", "-t", help="Repeatable")] = [],  # noqa: B006
    attr: Annotated[
        list[str], typer.Option("--attr", "-a", help="Kind-schema field, key=value, repeatable")
    ] = [],  # noqa: B006
) -> None:
    """Create a typed memory. Example:

    engram add project engram --attr name=engram --attr status=active -t oss
    """

    def action() -> None:
        runtime = _runtime()
        attributes = _parse_attrs(attr)
        if kind is MemoryKind.FACT and "statement" not in attributes:
            attributes["statement"] = content or title
        memory_id = runtime.commands.create_memory(
            CreateMemoryInput(
                kind=kind,
                title=title,
                content=content,
                attributes=attributes,
                slug=slug,
                tags=tuple(tag),
            ),
            _provenance(),
        )
        memory = runtime.queries.get_memory(memory_id)
        typer.secho(f"remembered {memory.kind.value} {memory.slug}", fg=typer.colors.GREEN)
        typer.echo(f"id: {memory.id}")

    _run(action)


@app.command(name="list")
def list_memories(
    kind: Annotated[MemoryKind | None, typer.Option(help="Filter by kind")] = None,
    tag: Annotated[str | None, typer.Option(help="Filter by tag")] = None,
    include_archived: Annotated[bool, typer.Option("--include-archived")] = False,
    limit: Annotated[int, typer.Option(min=1, max=200)] = 50,
) -> None:
    """List memories (current projected state)."""

    def action() -> None:
        runtime = _runtime()
        page = runtime.queries.list_memories(
            kind=kind, tag=tag, include_archived=include_archived, limit=limit
        )
        if not page.items:
            typer.echo('no memories yet — try `engram add fact "..."`')
            return
        for memory in page.items:
            typer.echo(_memory_line(memory))
        if page.next_cursor:
            typer.echo(f"… more (cursor {page.next_cursor})")

    _run(action)


@app.command()
def show(memory_id: Annotated[UUID, typer.Argument(help="The memory's UUID")]) -> None:
    """Show one memory in full, including its event timeline."""

    def action() -> None:
        runtime = _runtime()
        memory = runtime.queries.get_memory(MemoryId(memory_id))
        typer.echo(f"{memory.kind.value}: {memory.title}")
        typer.echo(f"id: {memory.id}   slug: {memory.slug}   version: {memory.version}")
        typer.echo(
            f"confidence: {memory.confidence:.2f}"
            f" (effective {memory.effective_confidence:.2f}"
            f"{', STALE' if memory.stale else ''})"
        )
        typer.echo(f"lifetime: {memory.lifetime_policy}   visibility: {memory.visibility}")
        if memory.tags:
            typer.echo(f"tags: {', '.join(memory.tags)}")
        if memory.attributes:
            typer.echo("attributes:")
            for key, value in sorted(memory.attributes.items()):
                if value not in (None, [], ()):
                    typer.echo(f"  {key}: {value}")
        if memory.content:
            typer.echo(f"\n{memory.content}\n")
        typer.echo("timeline:")
        for entry in runtime.timeline.memory_timeline(MemoryId(memory_id)):
            typer.echo(
                f"  #{entry.stream_seq}  {entry.occurred_at:%Y-%m-%d %H:%M:%S}Z"
                f"  {entry.event_type}  ({entry.actor})"
            )

    _run(action)


@app.command()
def rebuild() -> None:
    """Replay the event log through every projection from the beginning."""

    def action() -> None:
        runtime = _runtime()
        replayed = runtime.rebuild()
        typer.secho(f"rebuilt projections from {replayed} events", fg=typer.colors.GREEN)

    _run(action)


@app.command()
def status() -> None:
    """Show the space's health: event count, projection checkpoints, export drift."""
    _fail(_NOT_IMPLEMENTED)


@app.command()
def export() -> None:
    """Force a full markdown + NDJSON export to the git repository."""
    _fail(_NOT_IMPLEMENTED)


def _runtime() -> Runtime:
    return build_runtime(CliSettings())


def run() -> None:
    """Entry point for the ``engram`` script."""
    app()
