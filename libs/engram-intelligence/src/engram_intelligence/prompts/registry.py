"""The prompt registry: (name, version) -> immutable template (ADR-0013).

Mirrors the event and kind registries. Shipped versions are never edited in place —
a change is a new version file in ``library/``; old versions remain because past
proposals reference them (``prompt_name@version`` in proposal metadata).
"""

from dataclasses import dataclass
from pathlib import Path

import yaml

from engram_core.domain.errors import ValidationError

_LIBRARY_DIR = Path(__file__).parent / "library"


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
