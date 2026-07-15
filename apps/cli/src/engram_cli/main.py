"""The ``engram`` command. Real since M1: init, add, list, show, rebuild.
M2: search (the query language), status (drift detection), time travel
(``show --at`` / ``show --version``). M3: export, import (proposals or
--restore), link, and the ``git`` subcommands.

Exit-code contract: 0 success · 1 expected failure (mapped EngramError) ·
2 usage error (Typer's default) · 70 unexpected internal error.
"""

from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Annotated
from uuid import UUID

import typer

from engram_cli import __version__
from engram_cli.config import CliSettings
from engram_cli.runtime import Runtime, build_runtime
from engram_core.application.dto import CreateMemoryInput, MemoryReadModel, ProposalListItem
from engram_core.domain.errors import EngramError, ValidationError
from engram_core.domain.values import LinkRelation, MemoryId, MemoryKind, ProposalId
from engram_events import Provenance
from engram_export_git.repo import GitVersionControl
from engram_storage_sqlite.migrate import upgrade_to_head

app = typer.Typer(
    name="engram",
    help="Git-native, event-sourced, user-owned memory for AI assistants.",
    no_args_is_help=True,
)


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
def show(
    memory_id: Annotated[UUID, typer.Argument(help="The memory's UUID")],
    at: Annotated[
        datetime | None,
        typer.Option("--at", help="Time travel: state as of this UTC instant"),
    ] = None,
    version: Annotated[
        int | None,
        typer.Option("--version", "-v", min=1, help="Time travel: state after event #N"),
    ] = None,
) -> None:
    """Show one memory in full, including its event timeline.

    With --at or --version, reconstructs the memory exactly as it existed then
    by folding its event stream up to that point (works on deleted memories too).
    """

    def action() -> None:
        runtime = _runtime()
        if at is not None or version is not None:
            _show_snapshot(runtime, MemoryId(memory_id), at, version)
            return
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


def _show_snapshot(
    runtime: Runtime, memory_id: MemoryId, at: datetime | None, version: int | None
) -> None:
    snapshot = runtime.history.state_at(memory_id, at=at, version=version)
    when = f"--at {at:%Y-%m-%dT%H:%M:%SZ}" if at is not None else f"--version {version}"
    typer.secho(f"time travel ({when}) — state after event #{snapshot.version}:", dim=True)
    typer.echo(f"{snapshot.kind.value}: {snapshot.title}")
    typer.echo(f"id: {snapshot.id}   slug: {snapshot.slug}   version: {snapshot.version}")
    typer.echo(f"confidence: {snapshot.confidence:.2f} (as stored then; decay is a now-function)")
    typer.echo(f"lifetime: {snapshot.lifetime_policy}   visibility: {snapshot.visibility}")
    if snapshot.tags:
        typer.echo(f"tags: {', '.join(snapshot.tags)}")
    if snapshot.attributes:
        typer.echo("attributes:")
        for key, value in sorted(snapshot.attributes.items()):
            if value not in (None, [], ()):
                typer.echo(f"  {key}: {value}")
    if snapshot.content:
        typer.echo(f"\n{snapshot.content}\n")
    states = (("archived", snapshot.archived), ("DELETED", snapshot.deleted))
    flags = [flag for flag, on in states if on]
    if flags:
        typer.secho(f"state: {', '.join(flags)}", fg=typer.colors.YELLOW)


@app.command()
def search(
    query: Annotated[
        str,
        typer.Argument(
            help='Query language: kind:project status:active tag:oss confidence>0.8 "dark mode"'
        ),
    ],
    limit: Annotated[int, typer.Option(min=1, max=200)] = 20,
    cursor: Annotated[str | None, typer.Option(help="Opaque cursor from a previous page")] = None,
) -> None:
    """Query memories (ADR-0016). Free text is full-text match; everything else
    is an operator: kind: tag: slug: visibility: is: has: linked: updated: created:
    confidence> — plus any kind-schema attribute (status:active)."""

    def action() -> None:
        runtime = _runtime()
        page = runtime.search.query(query, cursor=cursor, limit=limit)
        if not page.items:
            typer.echo("no matches")
            return
        for hit in page.items:
            typer.echo(_memory_line(hit.memory))
            if hit.snippet:
                typer.secho(f"    {hit.snippet}", dim=True)
        if page.next_cursor:
            typer.echo(f"… more (--cursor {page.next_cursor})")

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
    """Show the space's health: event log totals and projection drift."""

    def action() -> None:
        settings = CliSettings()
        runtime = _runtime()
        report = runtime.status()
        typer.echo(f"space: {settings.resolved_db_path}")
        typer.echo(f"events: {report.event_count}   head: #{report.head_global_seq}")
        typer.echo(f"memories: {report.memory_count}")
        typer.echo("projections:")
        for projection in report.projections:
            marker = "ok" if projection.lag == 0 else f"DRIFTED (behind by {projection.lag})"
            typer.echo(f"  {projection.name:<12} checkpoint #{projection.checkpoint}  {marker}")
        if report.drifted:
            typer.secho(
                "projection drift detected — run `engram rebuild` (always safe)",
                fg=typer.colors.YELLOW,
            )

    _run(action)


@app.command()
def export(
    output: Annotated[
        Path | None, typer.Option("--output", "-o", help="Target directory (default: space repo)")
    ] = None,
    export_format: Annotated[
        str, typer.Option("--format", "-f", help="markdown | ndjson | all")
    ] = "all",
    incremental: Annotated[
        bool, typer.Option("--incremental", help="Extend events.ndjson instead of rewriting")
    ] = False,
) -> None:
    """Export the space to a portable repository: markdown + NDJSON + manifest.

    Deterministic: repeated exports without changes touch nothing.
    """

    def action() -> None:
        runtime = _runtime()
        root = output if output is not None else CliSettings().resolved_export_repo
        report = runtime.exporter.export(root, export_format=export_format, incremental=incremental)
        if not report.changed:
            typer.secho(f"export unchanged: {root}", fg=typer.colors.GREEN)
            return
        typer.secho(
            f"exported to {root}: {len(report.written)} written,"
            f" {len(report.deleted)} removed, {len(report.unchanged)} unchanged",
            fg=typer.colors.GREEN,
        )
        counts = report.manifest.counts
        typer.echo(
            f"memories: {counts.get('memories', 0)}   events: {counts.get('events', 0)}"
            f"   merkle: {report.manifest.merkle_root[:16]}…"
        )

    _run(action)


@app.command(name="import")
def import_(
    source: Annotated[Path, typer.Argument(help="Export repo, directory, .md, or .ndjson")],
    restore: Annotated[
        bool,
        typer.Option(
            "--restore",
            help="Reconstitute the event log verbatim (empty space only) instead of proposing",
        ),
    ] = False,
    title: Annotated[str | None, typer.Option(help="Proposal title")] = None,
) -> None:
    """Import memories. Default: validate and open a PROPOSAL — nothing changes
    memory until a human approves it. --restore rebuilds an empty space from an
    exported event log (the lossless round-trip path)."""

    def action() -> None:
        runtime = _runtime()
        if restore:
            report = runtime.importer.restore(source)
            replayed = runtime.rebuild()
            typer.secho(
                f"restored {report.events} events across {report.streams} streams;"
                f" projections rebuilt from {replayed} events",
                fg=typer.colors.GREEN,
            )
            return
        result = runtime.importer.import_documents(source, _provenance(), title=title)
        if result.proposal_id is None:
            typer.echo(f"nothing to propose — {result.unchanged} document(s) match current state")
            return
        typer.secho(
            f"opened proposal {result.proposal_id}: {result.created} new,"
            f" {result.edited} edited, {result.unchanged} unchanged"
            f" ({result.links} link changes, {result.evidence} evidence additions)",
            fg=typer.colors.GREEN,
        )
        typer.echo(
            f"review it: engram proposals show {result.proposal_id}"
            f" && engram proposals approve {result.proposal_id}"
            f" && engram proposals merge {result.proposal_id}"
        )

    _run(action)


@app.command()
def link(
    source_id: Annotated[UUID, typer.Argument(help="Source memory UUID")],
    target_id: Annotated[UUID, typer.Argument(help="Target memory UUID")],
    relation: Annotated[str, typer.Argument(help="about|involves|part_of|owned_by|…")],
) -> None:
    """Create a typed edge between two memories (tier-1 graph, ADR-0010)."""

    def action() -> None:
        runtime = _runtime()
        try:
            resolved = LinkRelation(relation)
        except ValueError:
            raise ValidationError(
                f"unknown relation {relation!r}; one of: " + ", ".join(sorted(set(LinkRelation)))
            ) from None
        runtime.commands.link_memories(
            MemoryId(source_id), MemoryId(target_id), resolved, _provenance()
        )
        typer.secho(f"linked {source_id} -{relation}-> {target_id}", fg=typer.colors.GREEN)

    _run(action)


proposals_app = typer.Typer(
    name="proposals",
    help="The review queue: nothing changes memory without an approved merge (ADR-0018).",
    no_args_is_help=True,
)
app.add_typer(proposals_app)


def _proposal_line(item: ProposalListItem) -> str:
    return (
        f"{item.id}  {item.status:<9} {item.draft_count:>3} draft(s)"
        f"  by {item.opened_by:<8} {item.created_at:%Y-%m-%d %H:%M}Z  {item.title}"
    )


@proposals_app.command(name="list")
def proposals_list(
    status: Annotated[
        str | None, typer.Option(help="pending | approved | rejected | merged | undone")
    ] = None,
    limit: Annotated[int, typer.Option(min=1, max=200)] = 50,
) -> None:
    """The review queue, newest first."""

    def action() -> None:
        runtime = _runtime()
        page = runtime.proposal_queries.list_proposals(status=status, limit=limit)
        if not page.items:
            typer.echo("no proposals" + (f" with status {status}" if status else ""))
            return
        for item in page.items:
            typer.echo(_proposal_line(item))

    _run(action)


@proposals_app.command(name="show")
def proposals_show(
    proposal_id: Annotated[UUID, typer.Argument(help="The proposal's UUID")],
) -> None:
    """Inspect one proposal: status, review note, and every draft intent."""

    def action() -> None:
        runtime = _runtime()
        detail = runtime.proposal_queries.get_proposal(ProposalId(proposal_id))
        typer.echo(f"proposal: {detail.title}")
        typer.echo(f"id: {detail.id}   status: {detail.status}   version: {detail.version}")
        if detail.description:
            typer.echo(f"description: {detail.description}")
        if detail.review_note:
            typer.echo(f"review note: {detail.review_note}")
        typer.echo(f"drafts ({len(detail.drafts)}):")
        for index, draft in enumerate(detail.drafts, start=1):
            op = draft.get("op", draft.get("event_type", "?"))
            target = draft.get("memory_id") or draft.get("source_id") or draft.get("stream_id")
            base = draft.get("base_version")
            summary = ", ".join(
                f"{key}={value!r}"
                for key, value in sorted(draft.items())
                if key
                not in ("op", "draft_schema_version", "memory_id", "source_id", "base_version")
                and value not in (None, [], {}, "")
            )
            base_note = f" (base v{base})" if base is not None else ""
            typer.echo(f"  #{index} {op} -> {target}{base_note}")
            if summary:
                typer.echo(f"      {summary}")
        if detail.merged_event_ids:
            typer.echo(f"merged events: {len(detail.merged_event_ids)}")

    _run(action)


@proposals_app.command(name="approve")
def proposals_approve(
    proposal_id: Annotated[UUID, typer.Argument()],
    note: Annotated[str | None, typer.Option("--note", "-n")] = None,
) -> None:
    """Approve a pending proposal (merge is a separate, explicit step)."""

    def action() -> None:
        _runtime().proposals.approve_proposal(ProposalId(proposal_id), note, _provenance())
        typer.secho(f"approved {proposal_id}", fg=typer.colors.GREEN)

    _run(action)


@proposals_app.command(name="reject")
def proposals_reject(
    proposal_id: Annotated[UUID, typer.Argument()],
    note: Annotated[str | None, typer.Option("--note", "-n")] = None,
) -> None:
    """Reject a pending proposal; its drafts never become events."""

    def action() -> None:
        _runtime().proposals.reject_proposal(ProposalId(proposal_id), note, _provenance())
        typer.secho(f"rejected {proposal_id}", fg=typer.colors.YELLOW)

    _run(action)


@proposals_app.command(name="merge")
def proposals_merge(
    proposal_id: Annotated[UUID, typer.Argument()],
) -> None:
    """Execute an approved proposal: every draft is re-validated by the aggregate
    against current state; conflicts abort the whole merge."""

    def action() -> None:
        appended = _runtime().proposals.merge_proposal(ProposalId(proposal_id), _provenance())
        typer.secho(
            f"merged {proposal_id}: {len(appended)} event(s) appended", fg=typer.colors.GREEN
        )

    _run(action)


@proposals_app.command(name="undo")
def proposals_undo(
    proposal_id: Annotated[UUID, typer.Argument()],
    note: Annotated[str | None, typer.Option("--note", "-n")] = None,
) -> None:
    """Compensate a merged proposal: one inverse event per merged event, in reverse
    order. Refused if anything changed since the merge. History is never rewritten."""

    def action() -> None:
        compensating = _runtime().proposals.undo_proposal(
            ProposalId(proposal_id), note, _provenance()
        )
        typer.secho(
            f"undone {proposal_id}: {len(compensating)} compensating event(s) appended",
            fg=typer.colors.GREEN,
        )

    _run(action)


git_app = typer.Typer(name="git", help="Version the export repository (git consumes exports).")
app.add_typer(git_app)


def _vcs() -> "GitVersionControl":
    return GitVersionControl(CliSettings().resolved_export_repo)


@git_app.command(name="init")
def git_init() -> None:
    """Initialize the export repository as a git repo (idempotent)."""

    def action() -> None:
        root = CliSettings().resolved_export_repo
        vcs = _vcs()
        vcs.init()
        typer.secho(f"git repository ready: {root}", fg=typer.colors.GREEN)

    _run(action)


@git_app.command(name="status")
def git_status() -> None:
    """Show uncommitted changes in the export repository."""

    def action() -> None:
        changes = _vcs().status()
        if not changes:
            typer.echo("clean — the committed export matches the working tree")
            return
        for line in changes:
            typer.echo(line)

    _run(action)


@git_app.command(name="commit")
def git_commit(
    message: Annotated[str | None, typer.Option("--message", "-m")] = None,
) -> None:
    """Export, then commit the export repository. Never touches runtime state."""

    def action() -> None:
        runtime = _runtime()
        root = CliSettings().resolved_export_repo
        report = runtime.exporter.export(root)
        vcs = _vcs()
        counts = report.manifest.counts
        sha = vcs.commit(
            (),
            message
            or (
                f"engram export: {counts.get('memories', 0)} memories,"
                f" {counts.get('events', 0)} events (head #{report.manifest.head_global_seq})"
            ),
        )
        typer.secho(f"committed {sha[:12]}", fg=typer.colors.GREEN)

    _run(action)


def _runtime() -> Runtime:
    return build_runtime(CliSettings())


def run() -> None:
    """Entry point for the ``engram`` script."""
    app()
