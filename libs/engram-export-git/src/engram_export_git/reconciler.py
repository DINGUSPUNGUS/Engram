"""Inbound reconciler: user edits to the export repo -> events.

Implements the ``MarkdownSync`` port. Diffs the working tree against the state
recorded in the manifest, parses changed documents, and produces
``MemoryEditedExternally`` envelopes for the command side to validate and append.
This is deliberately the *only* place where files influence the event log
(ADR-0001). Deferred to roadmap phase 4; stubs define the boundary.
"""

from collections.abc import Sequence
from pathlib import Path

from engram_events import EventEnvelope, EventRegistry


class GitReconciler:
    """Translates external markdown edits into candidate events."""

    def __init__(self, repo_root: Path, registry: EventRegistry) -> None:
        self._repo_root = repo_root
        self._registry = registry

    def export_paths(self) -> Sequence[Path]:
        """Paths currently owned by the exporter (from the manifest)."""
        raise NotImplementedError

    def import_external_changes(self) -> Sequence[EventEnvelope]:
        """Detect and translate user edits. Returned envelopes are *candidates* —
        not yet appended; conflict checks happen on append like any other write."""
        raise NotImplementedError
