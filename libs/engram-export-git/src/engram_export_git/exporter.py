"""The export projection: event log -> markdown files + NDJSON + git commits.

Implements the ``Projection`` protocol. Writes are batched: a group of envelopes
becomes one commit with a descriptive message (e.g. ``memory(kahnya-branding):
edited``). A process-wide file lock serializes export commits (ADR-0001's
single-writer note). Stubs.
"""

from pathlib import Path

from engram_core.domain.ports import MemoryQuery, VersionControl
from engram_events import EventEnvelope


class MarkdownExportProjection:
    """Folds events into the user-owned export repository."""

    def __init__(self, repo_root: Path, vcs: VersionControl, query: MemoryQuery) -> None:
        self._repo_root = repo_root
        self._vcs = vcs
        self._query = query

    @property
    def name(self) -> str:
        return "markdown-export"

    def handles(self, event_type: str) -> bool:
        return event_type.startswith("Memory")

    def apply(self, envelope: EventEnvelope) -> None:
        """Rewrite the affected markdown file, append the envelope to the NDJSON
        export, update the manifest, and commit."""
        raise NotImplementedError

    def checkpoint(self) -> int:
        """Last exported global_seq, read from the manifest."""
        raise NotImplementedError

    def reset(self) -> None:
        """Clear exported files (a fresh export follows). Never rewrites git history."""
        raise NotImplementedError
