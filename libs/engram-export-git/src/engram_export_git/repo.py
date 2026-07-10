"""GitPython adapter implementing the ``VersionControl`` port. Stubs.

GitPython objects never leak past this module; failures surface as
``StorageError``.
"""

from collections.abc import Sequence
from pathlib import Path


class GitVersionControl:
    """Thin, injectable facade over one git repository."""

    def __init__(self, repo_root: Path) -> None:
        self._repo_root = repo_root

    def commit(self, paths: Sequence[Path], message: str) -> str:
        """Stage ``paths`` and commit; returns the new commit sha.

        Raises:
            StorageError: repo missing, locked, or the commit failed.
        """
        raise NotImplementedError

    def head(self) -> str | None:
        """Current HEAD sha, or ``None`` on an empty repository."""
        raise NotImplementedError
