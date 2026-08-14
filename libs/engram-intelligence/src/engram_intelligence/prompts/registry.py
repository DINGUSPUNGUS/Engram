"""The prompt registry: (name, version) -> immutable template (ADR-0013).

Mirrors the event and kind registries. Shipped versions are never edited in place —
a change is a new version file in ``library/``; old versions remain because past
proposals reference them (``prompt_name@version`` in proposal metadata).
"""

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

import yaml

from engram_core.domain.errors import ValidationError

_LIBRARY_DIR = Path(__file__).parent / "library"
_LOCK_PATH = Path(__file__).parent / "library.lock.json"


@dataclass(frozen=True, slots=True)
class PromptTemplate:
    """One immutable prompt version.

    ``expected_output`` documents the contract the response parser relies on; the
    evaluation score is NOT stored here — it lives in evaluations/results/baseline.json
    (derived, like every other score — ADR-0009 thinking applied to prompts).
    """

    name: str
    version: int
    author: str
    stage: str
    body: str
    expected_output: str = ""
    model_hints: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.version < 1:
            raise ValidationError(f"prompt version must be >= 1: {self.name}@{self.version}")
        if not self.body.strip():
            raise ValidationError(f"prompt body is empty: {self.name}@{self.version}")

    @property
    def qualified_name(self) -> str:
        """The audit-trail identifier stamped into proposal metadata."""
        return f"{self.name}@{self.version}"

    @property
    def fingerprint(self) -> str:
        """Content hash of everything that defines this version's behavior.

        ADR-0013 says a shipped version is immutable and a change is a new
        version file — this is what actually catches a violation: the registry
        alone only rejects a *duplicate* (name, version) key, so an in-place
        edit that keeps the version number silently changes what
        ``prompt_name@version`` in a proposal's provenance meant, with nothing
        to notice (the P1 gap the fingerprint closes). Not the raw file bytes:
        frontmatter key order or incidental whitespace outside the body
        doesn't change behavior and shouldn't false-positive.
        """
        canonical = "\x1f".join(
            (
                self.name,
                str(self.version),
                self.author,
                self.stage,
                self.body,
                self.expected_output,
                "\x1e".join(self.model_hints),
            )
        )
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


class PromptRegistry:
    """Lookup by (name, version); versions are append-only."""

    def __init__(self) -> None:
        self._templates: dict[tuple[str, int], PromptTemplate] = {}

    def register(self, template: PromptTemplate) -> None:
        key = (template.name, template.version)
        if key in self._templates:
            raise ValidationError(f"prompt version already registered: {template.qualified_name}")
        self._templates[key] = template

    def get(self, name: str, version: int | None = None) -> PromptTemplate:
        """Fetch an exact version, or the latest when ``version`` is None.

        Raises:
            ValidationError: unknown prompt or version.
        """
        if version is not None:
            try:
                return self._templates[(name, version)]
            except KeyError:
                raise ValidationError(f"unknown prompt: {name}@{version}") from None
        versions = self.versions(name)
        if not versions:
            raise ValidationError(f"unknown prompt: {name}")
        return self._templates[(name, versions[-1])]

    def versions(self, name: str) -> tuple[int, ...]:
        """All registered versions of a prompt, ascending."""
        return tuple(sorted(v for (n, v) in self._templates if n == name))

    def all(self) -> tuple[PromptTemplate, ...]:
        """Every registered template, ordered by (name, version)."""
        return tuple(self._templates[key] for key in sorted(self._templates))


def load_library(directory: Path | None = None) -> PromptRegistry:
    """Load every ``*.md`` prompt file (YAML frontmatter + body) into a registry.

    Format of record: docs/intelligence.md §3. Defaults to the shipped library.

    Raises:
        ValidationError: malformed frontmatter, missing required keys, or a
            duplicate (name, version).
    """
    registry = PromptRegistry()
    for path in sorted((directory or _LIBRARY_DIR).glob("*.md")):
        registry.register(_parse_prompt_file(path))
    return registry


def library_fingerprints(registry: PromptRegistry) -> dict[str, str]:
    """``{qualified_name: fingerprint}`` for every template in ``registry`` —
    the shape ``library.lock.json`` commits and ``verify_library_lock`` checks
    against."""
    return {template.qualified_name: template.fingerprint for template in registry.all()}


def verify_library_lock(
    registry: PromptRegistry | None = None, lock_path: Path | None = None
) -> tuple[str, ...]:
    """Compare the library's actual content fingerprints against the committed
    lock file. Returns a description per mismatch (empty = lock holds); does
    not raise, so callers (a test, a CLI check) choose how to report it.

    A mismatch means either a shipped version's file was edited in place
    without a version bump (ADR-0013 violation — revert, or bump the version)
    or the lock file is stale after a deliberate new version (regenerate it in
    the same change: ``library_fingerprints(load_library())``).
    """
    registry = registry if registry is not None else load_library()
    actual = library_fingerprints(registry)
    lock_file = lock_path or _LOCK_PATH
    if not lock_file.exists():
        return (f"lock file missing: {lock_file}",)
    committed = json.loads(lock_file.read_text(encoding="utf-8")).get("fingerprints", {})
    mismatches = []
    for qualified_name, fingerprint in sorted(actual.items()):
        expected = committed.get(qualified_name)
        if expected is None:
            mismatches.append(f"{qualified_name}: not in lock file (new version, unlocked)")
        elif expected != fingerprint:
            mismatches.append(
                f"{qualified_name}: content changed but version did not"
                f" (locked {expected[:12]}…, actual {fingerprint[:12]}…)"
            )
    for qualified_name in sorted(set(committed) - set(actual)):
        mismatches.append(f"{qualified_name}: locked but no longer shipped")
    return tuple(mismatches)


def _parse_prompt_file(path: Path) -> PromptTemplate:
    text = path.read_text(encoding="utf-8-sig")
    if not text.startswith("---"):
        raise ValidationError(f"prompt file has no frontmatter: {path.name}")
    try:
        _, frontmatter, body = text.split("---", 2)
    except ValueError:
        raise ValidationError(f"prompt frontmatter is unterminated: {path.name}") from None
    try:
        meta = yaml.safe_load(frontmatter)
    except yaml.YAMLError as exc:
        raise ValidationError(f"prompt frontmatter is not YAML ({path.name}): {exc}") from exc
    if not isinstance(meta, dict):
        raise ValidationError(f"prompt frontmatter must be a mapping: {path.name}")
    missing = [key for key in ("name", "version", "author", "stage") if key not in meta]
    if missing:
        raise ValidationError(f"prompt {path.name} lacks frontmatter keys: {', '.join(missing)}")
    return PromptTemplate(
        name=str(meta["name"]),
        version=int(meta["version"]),
        author=str(meta["author"]),
        stage=str(meta["stage"]),
        body=body.strip("\n"),
        expected_output=str(meta.get("expected_output", "")),
        model_hints=tuple(str(hint) for hint in meta.get("model_hints", ())),
    )
