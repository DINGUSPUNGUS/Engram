"""Inbound reconciler: user edits to the export repo -> events.

Implements the ``MarkdownSync`` port. Diffs the working tree against the state
recorded in the manifest, parses changed documents, and produces
``MemoryEditedExternally`` envelopes for the command side to validate and append.
This is deliberately the *only* place where files influence the event log
(ADR-0001). ``import_external_changes`` (the diff → candidate-envelope half)
remains deferred; ``export_paths`` needed nothing beyond the manifest ``export``
already writes, so ADR-0021 §2's ``/settings`` implements it now.
"""

from collections.abc import Sequence
from pathlib import Path

from engram_events import EventEnvelope, EventRegistry
from engram_export_git import layout
from engram_export_git.manifest import parse_manifest


class GitReconciler:
    """Translates external markdown edits into candidate events."""

    def __init__(self, repo_root: Path, registry: EventRegistry) -> None:
        self._repo_root = repo_root
        self._registry = registry

    def export_paths(self) -> Sequence[Path]:
        """Paths currently owned by the exporter, read from the last-written
        manifest. Empty for a space that has never exported."""
        manifest_path = self._repo_root / layout.MANIFEST_PATH
        if not manifest_path.exists():
            return ()
        manifest = parse_manifest(manifest_path.read_text(encoding="utf-8"))
        owned = {manifest_path, *(self._repo_root / rel for rel in manifest.files)}
        return tuple(sorted(owned))

    def import_external_changes(self) -> Sequence[EventEnvelope]:
        """Detect and translate user edits. Returned envelopes are *candidates* —
        not yet appended; conflict checks happen on append like any other write."""
        raise NotImplementedError
