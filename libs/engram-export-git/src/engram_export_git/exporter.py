"""The export engine: projections + event log → a portable repository.

Contract (docs/export-format.md, ADR-0017):

- **Deterministic**: the same space always produces byte-identical content files;
  repeated exports with no changes touch nothing (the manifest's volatile fields
  are refreshed only when content changed).
- **Complete**: markdown (human face), memories.ndjson (interchange face), and
  events.ndjson (the replayable log — the restore path).
- **Non-destructive outside its lanes**: only files the layout owns are written
  or deleted; anything else in the repository is left alone.

The engine talks to ports only (``MemoryQuery``, ``EventStore``) — it never
imports the storage adapter.
"""

import time
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath

from engram_core.application.dto import MemoryReadModel
from engram_core.domain.errors import ValidationError
from engram_core.domain.ports import MemoryQuery
from engram_core.domain.values import MemoryKind
from engram_events import EventStore
from engram_export_git import layout, ndjson
from engram_export_git.frontmatter import iso_utc, render_document
from engram_export_git.manifest import (
    EXPORT_FORMAT_VERSION,
    MANIFEST_SCHEMA_VERSION,
    Manifest,
    merkle_root,
    parse_manifest,
    sha256_hex,
)

_PAGE_SIZE = 200
_EVENT_BATCH = 500

FORMAT_MARKDOWN = "markdown"
FORMAT_NDJSON = "ndjson"
FORMAT_ALL = "all"

_README = """\
# Your engram memory

This repository is the portable, human-readable face of an [engram](https://github.com/)
memory space. It is **generated** — `engram export` owns the layout:

- `memory/<kind>/<slug>.md` — one file per memory: YAML frontmatter (identity,
  spine metadata, links, attributes) + your narrative + an append-only Evidence
  section.
- `timeline/events.ndjson` — the complete event log. This is the true history:
  `engram import --restore` rebuilds an identical database from it anywhere.
- `metadata/memories.ndjson` — current state as one JSON object per line, for
  other tools.
- `manifest.json` — counts, per-file sha256 checksums, and a Merkle-style root.

You may edit the markdown files; feed edits back with `engram import <path>`,
which opens *proposals* — nothing changes memory without an approved event.
"""


@dataclass(frozen=True, slots=True)
class ExportReport:
    written: tuple[str, ...]
    deleted: tuple[str, ...]
    unchanged: tuple[str, ...]
    manifest: Manifest

    @property
    def changed(self) -> bool:
        return bool(self.written or self.deleted)


class ExportEngine:
    """Writes one export repository from the read side + the event log."""

    def __init__(self, query: MemoryQuery, store: EventStore, engine_version: str) -> None:
        self._query = query
        self._store = store
        self._engine_version = engine_version

    def export(
        self,
        root: Path,
        *,
        export_format: str = FORMAT_ALL,
        incremental: bool = False,
    ) -> ExportReport:
        """Export the space into ``root``. Returns what changed.

        Raises:
            ValidationError: unknown format, or (incremental) a manifest that
                cannot be parsed.
        """
        if export_format not in (FORMAT_MARKDOWN, FORMAT_NDJSON, FORMAT_ALL):
            raise ValidationError(f"unknown export format: {export_format!r}")
        started = time.monotonic()
        root.mkdir(parents=True, exist_ok=True)
        previous = self._read_previous_manifest(root)

        desired: dict[PurePosixPath, bytes] = {
            PurePosixPath(layout.README_PATH): _README.encode("utf-8")
        }

        memories = self._all_memories()
        counts = {
            "memories": len(memories),
            "links": sum(len(m.links) for m in memories),
            "relationship_objects": sum(1 for m in memories if m.kind is MemoryKind.RELATIONSHIP),
        }

        if export_format in (FORMAT_MARKDOWN, FORMAT_ALL):
            for memory in memories:
                relpath = layout.memory_relpath(memory.kind, memory.slug)
                desired[relpath] = render_document(memory).encode("utf-8")
        if export_format in (FORMAT_NDJSON, FORMAT_ALL):
            records = [
                ndjson.dumps(ndjson.memory_to_record(m))
                for m in sorted(memories, key=lambda m: str(m.id))
            ]
            desired[layout.MEMORIES_NDJSON_PATH] = (
                ("\n".join(records) + "\n") if records else ""
            ).encode("utf-8")

        head_global_seq = 0
        event_count = 0
        if export_format in (FORMAT_NDJSON, FORMAT_ALL):
            head_global_seq, event_count, events_bytes = self._events_bytes(
                root, previous, incremental=incremental
            )
            desired[layout.EVENTS_PATH] = events_bytes
        counts["events"] = event_count

        written, unchanged = self._write_all(root, desired)
        deleted = self._delete_orphans(root, desired, export_format)

        files = {str(path): sha256_hex(data) for path, data in desired.items()}
        candidate = Manifest(
            manifest_schema_version=MANIFEST_SCHEMA_VERSION,
            export_format_version=EXPORT_FORMAT_VERSION,
            engine_version=self._engine_version,
            engine_git_commit=previous.engine_git_commit if previous else None,
            generated_at=iso_utc(datetime.now(UTC)),
            duration_ms=int((time.monotonic() - started) * 1000),
            head_global_seq=head_global_seq,
            counts=counts,
            files=files,
            merkle_root=merkle_root(files),
        )
        if candidate.content_equal(previous):
            manifest = previous
            assert manifest is not None
        else:
            manifest = candidate
            layout.resolve_inside(root, layout.MANIFEST_PATH).write_bytes(
                manifest.to_json().encode("utf-8")
            )
            written = (*written, str(layout.MANIFEST_PATH))
        return ExportReport(
            written=written, deleted=deleted, unchanged=unchanged, manifest=manifest
        )

    # -- pieces -------------------------------------------------------------------

    def _read_previous_manifest(self, root: Path) -> Manifest | None:
        manifest_path = layout.resolve_inside(root, layout.MANIFEST_PATH)
        if not manifest_path.exists():
            return None
        return parse_manifest(manifest_path.read_text(encoding="utf-8"))

    def _all_memories(self) -> list[MemoryReadModel]:
        collected: list[MemoryReadModel] = []
        cursor: str | None = None
        while True:
            page = self._query.list_memories(include_archived=True, cursor=cursor, limit=_PAGE_SIZE)
            collected.extend(page.items)
            if page.next_cursor is None:
                return collected
            cursor = page.next_cursor

    def _events_bytes(
        self, root: Path, previous: Manifest | None, *, incremental: bool
    ) -> tuple[int, int, bytes]:
        """Serialize the event log; incrementally extend the previous file when safe."""
        existing = b""
        after = 0
        events_path = layout.resolve_inside(root, layout.EVENTS_PATH)
        if incremental and previous is not None and events_path.exists():
            on_disk = events_path.read_bytes()
            recorded = previous.files.get(str(layout.EVENTS_PATH))
            if recorded is not None and sha256_hex(on_disk) == recorded:
                existing = on_disk
                after = previous.head_global_seq
        lines: list[str] = []
        head = after
        count = self._count_lines(existing) if existing else 0
        while True:
            batch = self._store.read_all(after_global_seq=after, limit=_EVENT_BATCH)
            if not batch:
                break
            for envelope in batch:
                lines.append(ndjson.dumps(ndjson.envelope_to_record(envelope)))
                count += 1
            last = batch[-1].global_seq
            assert last is not None
            head = after = last
        appended = ("\n".join(lines) + "\n").encode("utf-8") if lines else b""
        return head, count, existing + appended

    @staticmethod
    def _count_lines(data: bytes) -> int:
        return data.count(b"\n")

    def _write_all(
        self, root: Path, desired: dict[PurePosixPath, bytes]
    ) -> tuple[tuple[str, ...], tuple[str, ...]]:
        written: list[str] = []
        unchanged: list[str] = []
        for relpath, data in sorted(desired.items(), key=lambda item: str(item[0])):
            target = layout.resolve_inside(root, relpath)
            if target.exists() and target.read_bytes() == data:
                unchanged.append(str(relpath))
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
            written.append(str(relpath))
        return tuple(written), tuple(unchanged)

    def _delete_orphans(
        self, root: Path, desired: dict[PurePosixPath, bytes], export_format: str
    ) -> tuple[str, ...]:
        """Remove managed markdown files whose memory no longer exists (renamed
        slugs, deletions). Only the layout's own lanes are touched."""
        if export_format == FORMAT_NDJSON:
            return ()
        keep = {str(path) for path in desired}
        deleted: list[str] = []
        memory_root = root / str(layout.MEMORY_DIR)
        if not memory_root.exists():
            return ()
        for path in sorted(memory_root.rglob("*.md")):
            rel = PurePosixPath(path.relative_to(root).as_posix())
            if str(rel) not in keep:
                path.unlink()
                deleted.append(str(rel))
        return tuple(deleted)


def iter_ndjson_lines(data: bytes) -> Iterable[str]:
    """Split NDJSON bytes into lines (helper shared with the importer).

    Tolerates a UTF-8 BOM: our own exports never carry one, but files that passed
    through Windows tooling often do."""
    for line in data.decode("utf-8-sig").splitlines():
        stripped = line.strip()
        if stripped:
            yield stripped


__all__ = [
    "FORMAT_ALL",
    "FORMAT_MARKDOWN",
    "FORMAT_NDJSON",
    "ExportEngine",
    "ExportReport",
    "iter_ndjson_lines",
]
