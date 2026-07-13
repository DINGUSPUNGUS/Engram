"""Markdown (de)serialization: YAML frontmatter + body + structured evidence.

Rendering is **hand-written, not yaml.dump**: byte-identical output is a contract
(docs/export-format.md), so we control every character. Strings are emitted as JSON
string literals (JSON is a YAML subset), keys in a fixed documented order, lists
sorted where order carries no meaning. Parsing uses ``yaml.safe_load`` — humans may
edit these files, and any YAML that means the same thing must import the same way.

Document shape::

    ---
    id: …            # immutable identity (ADR-0003)
    kind: …          # one of the twelve
    schema_version: …
    …frontmatter…
    ---

    <narrative markdown body>

    ## Evidence

    ```yaml
    - type: quote
      value: "…"
    ```

The trailing ``## Evidence`` section is machine-managed (append-only spine data);
everything above it is the human's.
"""

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import yaml

from engram_core.application.dto import MemoryReadModel
from engram_core.domain.errors import ValidationError

EVIDENCE_HEADING = "## Evidence"
_EVIDENCE_MARKER = f"\n{EVIDENCE_HEADING}\n\n```yaml\n"
_FRONTMATTER_KEYS_DOC_ORDER = (
    "id, kind, schema_version, title, slug, created_at, updated_at, created_by, "
    "confidence, visibility, lifetime, lifetime_until, archived, pinned, user_weight, "
    "tags, links, attributes"
)


def iso_utc(moment: datetime) -> str:
    """Deterministic ISO-8601 UTC with ``Z`` (always second-or-finer precision)."""
    aware = moment if moment.tzinfo is not None else moment.replace(tzinfo=UTC)
    return aware.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _scalar(value: object) -> str:
    match value:
        case None:
            return "null"
        case bool():
            return "true" if value else "false"
        case int():
            return str(value)
        case float():
            return repr(value)
        case datetime():
            return json.dumps(iso_utc(value))
        case str():
            return json.dumps(value, ensure_ascii=False)
        case _:
            raise ValidationError(f"cannot render frontmatter scalar: {type(value).__name__}")


def _render_value(key: str, value: object, indent: int, lines: list[str]) -> None:
    pad = "  " * indent
    if isinstance(value, Mapping):
        lines.append(f"{pad}{key}:")
        for sub_key in sorted(str(k) for k in value):
            _render_value(sub_key, value[sub_key], indent + 1, lines)
    elif isinstance(value, Sequence) and not isinstance(value, str | bytes):
        if not value:
            lines.append(f"{pad}{key}: []")
            return
        lines.append(f"{pad}{key}:")
        for item in value:
            if isinstance(item, Mapping):
                item_keys = sorted(str(k) for k in item)
                first, rest = item_keys[0], item_keys[1:]
                lines.append(f"{pad}  - {first}: {_scalar(item[first])}")
                for sub_key in rest:
                    lines.append(f"{pad}    {sub_key}: {_scalar(item[sub_key])}")
            else:
                lines.append(f"{pad}  - {_scalar(item)}")
    else:
        lines.append(f"{pad}{key}: {_scalar(value)}")


def render_document(memory: MemoryReadModel) -> str:
    """Serialize a read model into frontmatter + body + evidence. Deterministic."""
    fields: list[tuple[str, object]] = [
        ("id", str(memory.id)),
        ("kind", memory.kind.value),
        ("schema_version", 1),
        ("title", memory.title),
        ("slug", memory.slug),
        ("created_at", memory.created_at),
        ("updated_at", memory.updated_at),
        ("created_by", memory.created_by),
        ("confidence", memory.confidence),
        ("visibility", memory.visibility),
        ("lifetime", memory.lifetime_policy),
    ]
    if memory.lifetime_until is not None:
        fields.append(("lifetime_until", memory.lifetime_until))
    if memory.archived:
        fields.append(("archived", True))
    if memory.pinned:
        fields.append(("pinned", True))
    if memory.user_weight is not None:
        fields.append(("user_weight", memory.user_weight))
    fields.append(("tags", sorted(memory.tags)))
    fields.append(
        (
            "links",
            [
                {"relation": link.relation, "target": str(link.target_id)}
                for link in sorted(
                    memory.links, key=lambda edge: (edge.relation, str(edge.target_id))
                )
            ],
        )
    )
    fields.append(
        ("attributes", {k: v for k, v in sorted(memory.attributes.items()) if v is not None})
    )

    lines: list[str] = ["---"]
    for key, value in fields:
        _render_value(key, value, 0, lines)
    lines.append("---")
    lines.append("")
    body = memory.content.rstrip()
    if body:
        lines.append(body)
    if memory.evidence:
        if body:
            lines.append("")
        lines.append(EVIDENCE_HEADING)
        lines.append("")
        lines.append("```yaml")
        for item in memory.evidence:
            lines.append(f"- type: {_scalar(item.evidence_type)}")
            lines.append(f"  value: {_scalar(item.value)}")
            if item.note is not None:
                lines.append(f"  note: {_scalar(item.note)}")
            if item.added_at is not None:
                lines.append(f"  added_at: {_scalar(item.added_at)}")
            if item.actor is not None:
                lines.append(f"  actor: {_scalar(item.actor)}")
        lines.append("```")
    return "\n".join(lines) + "\n"


@dataclass(frozen=True, slots=True)
class ParsedDocument:
    """A markdown document split into its machine-relevant parts (unvalidated)."""

    meta: dict[str, Any]
    body: str
    evidence: tuple[dict[str, Any], ...]


def parse_document(text: str) -> ParsedDocument:
    """Split a document into frontmatter dict, body, and evidence entries.

    Raises:
        ValidationError: missing/unparseable frontmatter or evidence block.
    """
    if not text.startswith("---\n"):
        raise ValidationError("document must start with '---' frontmatter")
    raw_meta, separator, remainder = text[4:].partition("\n---\n")
    if not separator:
        raise ValidationError("unterminated frontmatter block")
    try:
        meta = yaml.safe_load(raw_meta)
    except yaml.YAMLError as exc:
        raise ValidationError(f"invalid frontmatter YAML: {exc}") from exc
    if not isinstance(meta, dict):
        raise ValidationError("frontmatter must be a YAML mapping")

    body = remainder
    evidence: tuple[dict[str, Any], ...] = ()
    marker_at = remainder.rfind(_EVIDENCE_MARKER)
    if marker_at != -1:
        block = remainder[marker_at + len(_EVIDENCE_MARKER) :]
        fence_end = block.find("\n```")
        if fence_end == -1:
            raise ValidationError("unterminated evidence block")
        try:
            entries = yaml.safe_load(block[:fence_end])
        except yaml.YAMLError as exc:
            raise ValidationError(f"invalid evidence YAML: {exc}") from exc
        if not isinstance(entries, list) or not all(isinstance(e, dict) for e in entries):
            raise ValidationError("evidence block must be a YAML list of mappings")
        evidence = tuple(entries)
        body = remainder[:marker_at]
    return ParsedDocument(meta=meta, body=body.strip("\n"), evidence=evidence)
