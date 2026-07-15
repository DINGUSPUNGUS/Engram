"""Draft intents: what a proposal carries (ADR-0018).

A draft is a declarative *intent*, not an event — merge re-drives every intent
through the Memory aggregate's ``decide_*`` methods against current state, and only
that produces events. Each intent records ``base_version``: the target stream's
aggregate version when the proposal was opened (0 for creates). Merge-time conflict
detection compares it to the stream's head (ADR-0018 §2).

Wire form is a JSON-safe dict with ``draft_schema_version: 2`` and an ``op``
discriminator. M3 shipped ``draft_schema_version``-less, event-shaped drafts (v1);
``parse_draft`` upcasts them so old proposals merge forever. v1 drafts carry no
``base_version`` — they merge unchecked (``base_version=None``), documented legacy.
"""

import dataclasses
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from engram_core.domain.errors import ValidationError

DRAFT_SCHEMA_VERSION = 2


@dataclass(frozen=True, slots=True)
class CreateMemoryDraft:
    memory_id: UUID
    kind: str
    slug: str
    title: str
    content: str
    attributes: dict[str, object]
    attributes_schema_version: int
    tags: tuple[str, ...]
    confidence: float
    lifetime_policy: str
    lifetime_until: str | None
    visibility: str
    base_version: int | None = 0

    @property
    def stream_id(self) -> UUID:
        return self.memory_id


@dataclass(frozen=True, slots=True)
class EditMemoryDraft:
    memory_id: UUID
    base_version: int | None
    title: str | None = None
    content: str | None = None
    slug: str | None = None

    @property
    def stream_id(self) -> UUID:
        return self.memory_id


@dataclass(frozen=True, slots=True)
class TagMemoryDraft:
    memory_id: UUID
    base_version: int | None
    add: tuple[str, ...] = ()
    remove: tuple[str, ...] = ()

    @property
    def stream_id(self) -> UUID:
        return self.memory_id


@dataclass(frozen=True, slots=True)
class UpdateAttributesDraft:
    memory_id: UUID
    base_version: int | None
    changes: dict[str, object]

    @property
    def stream_id(self) -> UUID:
        return self.memory_id


@dataclass(frozen=True, slots=True)
class LinkDraft:
    source_id: UUID
    target_id: UUID
    relation: str
    base_version: int | None

    @property
    def stream_id(self) -> UUID:
        return self.source_id


@dataclass(frozen=True, slots=True)
class UnlinkDraft:
    source_id: UUID
    target_id: UUID
    relation: str
    base_version: int | None

    @property
    def stream_id(self) -> UUID:
        return self.source_id


@dataclass(frozen=True, slots=True)
class AddEvidenceDraft:
    memory_id: UUID
    base_version: int | None
    evidence_type: str
    value: str
    note: str | None = None

    @property
    def stream_id(self) -> UUID:
        return self.memory_id


@dataclass(frozen=True, slots=True)
class SetVisibilityDraft:
    memory_id: UUID
    base_version: int | None
    visibility: str
    allowed_actors: tuple[str, ...] = ()

    @property
    def stream_id(self) -> UUID:
        return self.memory_id


@dataclass(frozen=True, slots=True)
class SetLifetimeDraft:
    memory_id: UUID
    base_version: int | None
    lifetime_policy: str
    lifetime_until: str | None = None

    @property
    def stream_id(self) -> UUID:
        return self.memory_id


DraftIntent = (
    CreateMemoryDraft
    | EditMemoryDraft
    | TagMemoryDraft
    | UpdateAttributesDraft
    | LinkDraft
    | UnlinkDraft
    | AddEvidenceDraft
    | SetVisibilityDraft
    | SetLifetimeDraft
)

_OPS: dict[str, type] = {
    "create_memory": CreateMemoryDraft,
    "edit_memory": EditMemoryDraft,
    "tag_memory": TagMemoryDraft,
    "update_attributes": UpdateAttributesDraft,
    "link_memories": LinkDraft,
    "unlink_memories": UnlinkDraft,
    "add_evidence": AddEvidenceDraft,
    "set_visibility": SetVisibilityDraft,
    "set_lifetime": SetLifetimeDraft,
}
_OP_NAMES: dict[type, str] = {intent_type: op for op, intent_type in _OPS.items()}


def to_dict(intent: DraftIntent) -> dict[str, object]:
    """Wire form: JSON-safe, versioned, op-discriminated. Deterministic keys."""
    record: dict[str, object] = {
        "draft_schema_version": DRAFT_SCHEMA_VERSION,
        "op": _OP_NAMES[type(intent)],
    }
    for field in dataclasses.fields(intent):
        value = getattr(intent, field.name)
        if isinstance(value, UUID):
            value = str(value)
        elif isinstance(value, tuple):
            value = list(value)
        record[field.name] = value
    return record


def parse_draft(record: dict[str, Any]) -> DraftIntent:
    """Wire dict (v1 or v2) → typed intent.

    Raises:
        ValidationError: unknown op/version or malformed fields.
    """
    version = record.get("draft_schema_version")
    if version is None and "event_type" in record:
        record = _upcast_v1(record)
        version = DRAFT_SCHEMA_VERSION
    if version != DRAFT_SCHEMA_VERSION:
        raise ValidationError(f"unsupported draft schema version: {version!r}")
    op = record.get("op")
    intent_type = _OPS.get(str(op))
    if intent_type is None:
        raise ValidationError(f"unknown draft op: {op!r}")
    kwargs: dict[str, object] = {}
    try:
        for field in dataclasses.fields(intent_type):
            value = record.get(field.name)
            if field.name in ("memory_id", "source_id", "target_id"):
                value = UUID(str(value))
            elif field.name in ("tags", "add", "remove", "allowed_actors"):
                value = tuple(value or ())
            elif field.name in ("attributes", "changes"):
                value = dict(value or {})
            elif field.name == "base_version":
                value = int(value) if value is not None else None
            kwargs[field.name] = value
        return intent_type(**kwargs)  # type: ignore[no-any-return]
    except (TypeError, ValueError, KeyError) as exc:
        raise ValidationError(f"malformed {op} draft: {exc!r}") from exc


def _upcast_v1(record: dict[str, Any]) -> dict[str, Any]:
    """M3's event-shaped drafts → v2 intents. No base_version existed then, so
    these merge unchecked (documented legacy; ADR-0018)."""
    event_type = record.get("event_type")
    payload = dict(record.get("payload") or {})
    stream_id = record.get("stream_id")
    match event_type:
        case "MemoryCreated":
            return {
                "draft_schema_version": DRAFT_SCHEMA_VERSION,
                "op": "create_memory",
                "memory_id": payload.get("memory_id", stream_id),
                "kind": payload.get("kind"),
                "slug": payload.get("slug"),
                "title": payload.get("title"),
                "content": payload.get("content", ""),
                "attributes": payload.get("attributes", {}),
                "attributes_schema_version": payload.get("attributes_schema_version", 1),
                "tags": payload.get("tags", []),
                "confidence": payload.get("confidence", 0.6),
                "lifetime_policy": payload.get("lifetime_policy", "standard"),
                "lifetime_until": payload.get("lifetime_until"),
                "visibility": payload.get("visibility", "shared"),
                "base_version": 0,
            }
        case "MemoryLinked":
            return {
                "draft_schema_version": DRAFT_SCHEMA_VERSION,
                "op": "link_memories",
                "source_id": stream_id,
                "target_id": payload.get("target_id"),
                "relation": payload.get("relation"),
                "base_version": None,
            }
        case "MemoryEvidenceAdded":
            return {
                "draft_schema_version": DRAFT_SCHEMA_VERSION,
                "op": "add_evidence",
                "memory_id": stream_id,
                "evidence_type": payload.get("evidence_type"),
                "value": payload.get("value"),
                "note": payload.get("note"),
                "base_version": None,
            }
        case _:
            raise ValidationError(f"cannot upcast v1 draft of type {event_type!r}")


def parse_all(records: Sequence[dict[str, Any]]) -> tuple[DraftIntent, ...]:
    """Parse every draft, reporting all problems at once."""
    intents: list[DraftIntent] = []
    errors: list[str] = []
    for index, record in enumerate(records, start=1):
        try:
            intents.append(parse_draft(dict(record)))
        except ValidationError as exc:
            errors.append(f"draft #{index}: {exc}")
    if errors:
        raise ValidationError("proposal drafts are malformed:\n" + "\n".join(errors))
    return tuple(intents)
