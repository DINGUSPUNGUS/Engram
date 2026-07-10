"""On-disk layout of the export repository.

    <export-repo>/
    ├── memories/<type>/<slug>.md      # one file per live memory (frontmatter + body)
    ├── .engram/
    │   ├── events/<yyyy>-<mm>.ndjson  # append-only event export, month-sharded
    │   └── manifest.json              # uuid -> path map + last exported global_seq
    └── README.md                      # generated: explains the repo to humans

Filenames derive from mutable slugs; identity lives in frontmatter (ADR-0003).
The ``Slug`` value object's constrained alphabet is the path-traversal guard —
this module still asserts the resolved path stays inside the repo root.
"""

from pathlib import Path, PurePosixPath

from engram_core.domain.errors import ValidationError
from engram_core.domain.values import MemoryType, Slug

MEMORIES_DIR = PurePosixPath("memories")
ENGRAM_DIR = PurePosixPath(".engram")
EVENTS_DIR = ENGRAM_DIR / "events"
MANIFEST_PATH = ENGRAM_DIR / "manifest.json"


def memory_relpath(memory_type: MemoryType, slug: Slug) -> PurePosixPath:
    """Relative path of a memory's markdown file inside the export repo."""
    return MEMORIES_DIR / memory_type.value / f"{slug}.md"


def resolve_inside(repo_root: Path, relpath: PurePosixPath) -> Path:
    """Join and verify the result cannot escape the repository root.

    Raises:
        ValidationError: if the resolved path leaves ``repo_root``.
    """
    resolved = (repo_root / Path(relpath)).resolve()
    if not resolved.is_relative_to(repo_root.resolve()):
        raise ValidationError(f"path escapes export repo: {relpath}")
    return resolved
