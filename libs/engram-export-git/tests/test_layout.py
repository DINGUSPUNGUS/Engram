"""Layout contract: deterministic paths, and the traversal guard holds."""

from pathlib import Path, PurePosixPath

import pytest

from engram_core.domain.errors import ValidationError
from engram_core.domain.values import MemoryType, Slug
from engram_export_git.layout import memory_relpath, resolve_inside


@pytest.mark.unit
def test_memory_relpath_is_type_sharded() -> None:
    relpath = memory_relpath(MemoryType.PREFERENCE, Slug("kahnya-branding"))
    assert relpath == PurePosixPath("memories/preference/kahnya-branding.md")


@pytest.mark.unit
def test_resolve_inside_accepts_repo_paths(tmp_path: Path) -> None:
    resolved = resolve_inside(tmp_path, PurePosixPath("memories/fact/a.md"))
    assert resolved.is_relative_to(tmp_path)


@pytest.mark.unit
def test_resolve_inside_rejects_escapes(tmp_path: Path) -> None:
    with pytest.raises(ValidationError):
        resolve_inside(tmp_path, PurePosixPath("../outside.md"))
