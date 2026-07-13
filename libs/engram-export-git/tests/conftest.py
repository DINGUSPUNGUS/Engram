"""Fixtures over the shared harness (see export_harness.py)."""

from pathlib import Path

import pytest
from export_harness import Space, build_space, seed_rich_space

from engram_core.domain.values import MemoryId


@pytest.fixture
def space(tmp_path: Path) -> Space:
    return build_space(tmp_path / "space.db")


@pytest.fixture
def seeded(space: Space) -> dict[str, MemoryId]:
    return seed_rich_space(space)
