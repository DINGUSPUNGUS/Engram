"""The engram query language (ADR-0016): one grammar for CLI, REST, and MCP.

``parse_query`` turns a query string into a typed ``MemoryQuerySpec``. Terms are
whitespace-separated and ANDed; quoted phrases survive as phrases. Full-text match is
just the free-text operator — every bare word or phrase becomes an FTS term, quoted so
user input can never inject FTS5 syntax.

A ``key:value`` term that is not a reserved operator falls through to kind-attribute
equality **only when the key exists in some kind schema** (the KindRegistry is the
source of truth) — that is what makes the twelve kinds queryable without twelve query
surfaces (``status:active``), while tokens like ``https://…`` stay free text.

Relative dates (``updated:last30days``) resolve against the injected ``now`` so parsing
stays deterministic under test.
"""

import dataclasses
import re
import shlex
from datetime import UTC, datetime, timedelta

from engram_core.application.dto import ConfidenceFilter, MemoryQuerySpec
from engram_core.domain.errors import ValidationError
from engram_core.domain.kinds import KindRegistry
from engram_core.domain.values import MemoryKind, Visibility

_TERM_PATTERN = re.compile(r"^([A-Za-z_][A-Za-z0-9_]*)(>=|<=|>|<|:)(.*)$", re.DOTALL)
_LAST_N_DAYS_PATTERN = re.compile(r"^last(\d+)days$")
_HAS_VALUES = frozenset({"evidence", "links"})
_IS_VALUES = frozenset({"archived", "pinned", "stale"})
_RESERVED = frozenset(
    {"kind", "tag", "slug", "visibility", "is", "has", "updated", "created", "linked", "confidence"}
)


def known_attribute_keys(kinds: KindRegistry) -> frozenset[str]:
    """Every field name declared by any kind schema — the fallthrough vocabulary."""
    names: set[str] = set()
    for kind in MemoryKind:
        names.update(field.name for field in dataclasses.fields(kinds.attributes_type(kind)))
    return frozenset(names)


def _fts_term(word: str) -> str:
    """Quote one word/phrase for FTS5 MATCH — doubling embedded quotes disarms syntax."""
    return '"' + word.replace('"', '""') + '"'


def _parse_since(value: str, now: datetime) -> datetime:
    if value == "today":
        return now.replace(hour=0, minute=0, second=0, microsecond=0)
    if match := _LAST_N_DAYS_PATTERN.fullmatch(value):
        return now - timedelta(days=int(match.group(1)))
    try:
        return datetime.strptime(value, "%Y-%m-%d").replace(tzinfo=UTC)
    except ValueError:
        raise ValidationError(
            f"bad date {value!r}: expected today, last<N>days, or YYYY-MM-DD"
        ) from None


def _kind_prefix(value: str) -> str:
    """``linked:person/jude`` — the kind prefix is a readability nicety; slugs are
    globally unique, so only the part after ``/`` matters."""
    head, separator, _ = value.partition("/")
    return head + separator if separator and head.lower() in set(MemoryKind) else ""


class _Builder:
    """Accumulates terms, rejecting duplicates of single-valued operators."""

    def __init__(self, now: datetime) -> None:
        self._now = now
        self._single: dict[str, object] = {}
        self.text_terms: list[str] = []
        self.tags: list[str] = []
        self.attributes: list[tuple[str, str]] = []
        self.has: set[str] = set()

    def set_single(self, name: str, value: object) -> None:
        if name in self._single:
            raise ValidationError(f"duplicate operator: {name}")
        self._single[name] = value

    def comparison(self, name: str, op: str, value: str) -> None:
        if name != "confidence":
            raise ValidationError(f"comparison only applies to confidence, got {name!r}")
        try:
            number = float(value)
        except ValueError:
            raise ValidationError(f"confidence needs a number, got {value!r}") from None
        self.set_single("confidence", ConfidenceFilter(op=op, value=number))

    def operator(self, name: str, value: str) -> None:
        if not value:
            raise ValidationError(f"operator {name}: needs a value")
        match name:
            case "kind":
                try:
                    self.set_single("kind", MemoryKind(value.lower()))
                except ValueError:
                    raise ValidationError(f"unknown kind: {value!r}") from None
            case "tag":
                self.tags.append(value.strip().lower())
            case "slug":
                self.set_single("slug", value)
            case "visibility":
                try:
                    self.set_single("visibility", Visibility(value.lower()))
                except ValueError:
                    raise ValidationError(f"unknown visibility: {value!r}") from None
            case "is":
                if value not in _IS_VALUES:
                    raise ValidationError(f"is: expects one of {sorted(_IS_VALUES)}, got {value!r}")
                self.set_single(f"is:{value}", True)
            case "has":
                if value not in _HAS_VALUES:
                    raise ValidationError(
                        f"has: expects one of {sorted(_HAS_VALUES)}, got {value!r}"
                    )
                self.has.add(value)
            case "updated":
                self.set_single("updated_after", _parse_since(value, self._now))
            case "created":
                self.set_single("created_after", _parse_since(value, self._now))
            case "linked":
                self.set_single("linked", value.removeprefix(_kind_prefix(value)))
            case "confidence":
                raise ValidationError("confidence is a comparison: confidence>0.8, not a colon")
            case _:  # pre-checked against the schema vocabulary in parse_query
                self.attributes.append((name, value))

    def build(self) -> MemoryQuerySpec:
        single = self._single
        return MemoryQuerySpec(
            text=" ".join(self.text_terms) or None,
            kind=single.get("kind"),  # type: ignore[arg-type]
            tags=tuple(self.tags),
            slug=single.get("slug"),  # type: ignore[arg-type]
            attributes=tuple(self.attributes),
            confidence=single.get("confidence"),  # type: ignore[arg-type]
            updated_after=single.get("updated_after"),  # type: ignore[arg-type]
            created_after=single.get("created_after"),  # type: ignore[arg-type]
            has=frozenset(self.has),
            visibility=single.get("visibility"),  # type: ignore[arg-type]
            linked=single.get("linked"),  # type: ignore[arg-type]
            archived=True if single.get("is:archived") else None,
            pinned=True if single.get("is:pinned") else None,
            stale=True if single.get("is:stale") else None,
        )


def parse_query(query: str, *, now: datetime, kinds: KindRegistry) -> MemoryQuerySpec:
    """Parse one query string into a spec.

    Raises:
        ValidationError: empty query, unknown operator value, bad number/date,
            unbalanced quotes, or a duplicated single-valued operator.
    """
    try:
        tokens = shlex.split(query)
    except ValueError as exc:
        raise ValidationError(f"unbalanced quotes in query: {exc}") from exc
    if not tokens:
        raise ValidationError("empty query")
    attribute_keys = known_attribute_keys(kinds)
    builder = _Builder(now)
    for token in tokens:
        match = _TERM_PATTERN.fullmatch(token)
        name = match.group(1).lower() if match else ""
        if match and match.group(2) != ":":
            builder.comparison(name, match.group(2), match.group(3))
        elif match and (name in _RESERVED or name in attribute_keys):
            builder.operator(name, match.group(3))
        else:
            builder.text_terms.append(_fts_term(token))
    return builder.build()
