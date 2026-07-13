"""GitPython adapter implementing the ``VersionControl`` port.

Git is a **consumer of exported state** (ADR-0017): this adapter inits, inspects,
and commits the export repository — it never touches the runtime database, and
nothing in engram reads state back *out* of git. GitPython objects never leak
past this module; failures surface as ``StorageError``.
"""

from collections.abc import Sequence
from pathlib import Path

from git import GitCommandError, InvalidGitRepositoryError, Repo

from engram_core.domain.errors import StorageError


class GitVersionControl:
    """Thin, injectable facade over one git repository."""

    def __init__(self, repo_root: Path) -> None:
        self._repo_root = repo_root

    def is_repo(self) -> bool:
        try:
            Repo(self._repo_root)
            return True
        except Exception:  # InvalidGitRepositoryError, NoSuchPathError
            return False

    def init(self) -> None:
        """Create the repository if it does not exist (idempotent)."""
        try:
            self._repo_root.mkdir(parents=True, exist_ok=True)
            Repo.init(self._repo_root)
        except GitCommandError as exc:
            raise StorageError(f"git init failed: {exc}") from exc

    def status(self) -> Sequence[str]:
        """Changed/untracked paths relative to HEAD (porcelain-style)."""
        repo = self._open()
        try:
            lines = repo.git.status("--porcelain").splitlines()
        except GitCommandError as exc:
            raise StorageError(f"git status failed: {exc}") from exc
        return tuple(line for line in lines if line.strip())

    def commit(self, paths: Sequence[Path], message: str) -> str:
        """Stage ``paths`` (all changes when empty) and commit; returns the sha.

        Raises:
            StorageError: repo missing or the commit failed.
            ConflictError-free by design: an empty commit raises StorageError with
                a clear message instead.
        """
        repo = self._open()
        try:
            if paths:
                repo.index.add([str(path) for path in paths])
            else:
                repo.git.add("--all")
            if not repo.is_dirty(untracked_files=True) and _has_head(repo):
                raise StorageError("nothing to commit — the export is unchanged")
            commit = repo.index.commit(message)
            return commit.hexsha
        except GitCommandError as exc:
            raise StorageError(f"git commit failed: {exc}") from exc

    def head(self) -> str | None:
        repo = self._open()
        return repo.head.commit.hexsha if _has_head(repo) else None

    def _open(self) -> Repo:
        try:
            return Repo(self._repo_root)
        except InvalidGitRepositoryError as exc:
            raise StorageError(
                f"{self._repo_root} is not a git repository — run `engram git init` first"
            ) from exc
        except Exception as exc:  # NoSuchPathError etc.
            raise StorageError(f"cannot open git repository at {self._repo_root}: {exc}") from exc


def _has_head(repo: Repo) -> bool:
    try:
        _ = repo.head.commit
        return True
    except (ValueError, GitCommandError):
        return False
