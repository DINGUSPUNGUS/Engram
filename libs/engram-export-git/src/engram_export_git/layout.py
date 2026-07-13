"""On-disk layout of the export repository (docs/export-format.md).

    <export-repo>/
    ├── README.md                    # generated: explains the repo to humans
    ├── manifest.json                # counts, per-file checksums, merkle root
    ├── memory/
    │   ├── facts/<slug>.md          # one file per live memory, by kind (plural)
    │   ├── people/…  projects/…  relationships/…  (all twelve kinds)
    ├── timeline/
    │   └── events.ndjson            # the full event log — the restore path
    └── metadata/
        └── memories.ndjson          # current-state objects for foreign systems

Filenames derive from mutable slugs; identity lives in frontmatter (ADR-0003).
The ``Slug`` value object's constrained alphabet is the path-traversal guard —
``resolve_inside`` still asserts the resolved path stays inside the repo root.
"""

from pathlib import Path, PurePosixPath

from engram_core.domain.errors import ValidationError
from engram_core.domain.values import MemoryKind, Slug

MEMORY_DIR = PurePosixPath("memory")
TIMELINE_DIR = PurePosixPath("timeline")
METADATA_DIR = PurePosixPath("metadata")
EVENTS_PATH = TIMELINE_DIR / "events.ndjson"
MEMORIES_NDJSON_PATH = METADATA_DIR / "memories.ndjson"
MANIFEST_PATH = PurePosixPath("manifest.json")
README_PATH = PurePosixPath("README.md")

KIND_DIRS: dict[MemoryKind, str] = {
    MemoryKind.FACT: "facts",
    MemoryKind.PREFERENCE: "preferences",
    MemoryKind.PERSON: "people",
    MemoryKind.ORGANIZATION: "organizations",
    MemoryKind.PROJECT: "projects",
    MemoryKind.SKILL: "skills",
    MemoryKind.GOAL: "goals",
    MemoryKind.CONTACT: "contacts",
    MemoryKind.EVENT: "events",
    MemoryKind.LOCATION: "locations",
    MemoryKind.ASSET: "assets",
    MemoryKind.RELATIONSHIP: "relationships",
}


def memory_relpath(kind: MemoryKind, slug: Slug | str) -> PurePosixPath:
    """Relative path of a memory's markdown file inside the export repo."""
    return MEMORY_DIR / KIND_DIRS[kind] / f"{slug}.md"


def resolve_inside(repo_root: Path, relpath: PurePosixPath) -> Path:
    """Join and verify the result cannot escape the repository root.

    Raises:
        ValidationError: if the resolved path leaves ``repo_root``.
    """
    resolved = (repo_root / Path(relpath)).resolve()
    if not resolved.is_relative_to(repo_root.resolve()):
        raise ValidationError(f"path escapes export repo: {relpath}")
    return resolved
