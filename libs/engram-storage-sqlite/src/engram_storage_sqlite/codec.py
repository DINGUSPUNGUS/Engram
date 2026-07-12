"""Payload/provenance codec: dataclasses <-> JSON text columns.

Writing is easy (UUID -> str, datetime -> ISO-8601). Reading coerces back using the
payload dataclass's type hints, so replayed payloads are *typed* equal to what was
appended — the property the replay-determinism tests stand on. Upcasting happens
before coercion, via the event registry (ADR-0002).
"""

import dataclasses
import json
import types
import typing
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from engram_core.domain.errors import StorageError
from engram_events import EventRegistry, Provenance


def _json_default(value: object) -> str:
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, datetime):
        return value.astimezone(UTC).isoformat()
    raise TypeError(f"not JSON-encodable: {type(value)!r}")


def encode_payload(payload: object) -> str:
    """Serialize a registered payload dataclass instance to a JSON text column."""
    if not dataclasses.is_dataclass(payload) or isinstance(payload, type):
        raise StorageError(f"payload must be a dataclass instance: {type(payload)!r}")
    return json.dumps(dataclasses.asdict(payload), default=_json_default, sort_keys=True)


def encode_json(data: dict[str, Any] | list[Any]) -> str:
    """JSON-encode arbitrary payload-ish data (UUID/datetime aware)."""
    return json.dumps(data, default=_json_default, sort_keys=True)


def encode_provenance(provenance: Provenance) -> str:
    return json.dumps(dataclasses.asdict(provenance), sort_keys=True)


def decode_provenance(text: str) -> Provenance:
    data: dict[str, Any] = json.loads(text)
    return Provenance(**data)


def decode_payload(
    registry: EventRegistry, event_type: str, text: str, *, schema_version: int
) -> object:
    """Rehydrate a payload text column (any historical version) into the current,
    correctly-typed dataclass."""
    raw: dict[str, Any] = json.loads(text)
    migrated = registry.upcast(event_type, raw, schema_version)
    payload_type = registry.payload_type(event_type)
    hints = typing.get_type_hints(payload_type)
    coerced = {name: _coerce(value, hints.get(name, object)) for name, value in migrated.items()}
    try:
        return payload_type(**coerced)
    except TypeError as exc:
        raise StorageError(f"cannot rehydrate {event_type}: {exc}") from exc


def _coerce(value: Any, annotation: Any) -> Any:
    """Coerce a JSON value to its annotated type: UUID, datetime, tuples, optionals."""
    if value is None:
        return None
    origin = typing.get_origin(annotation)
    # X | None and typing.Union unwrap to the first non-None arm.
    if origin in (types.UnionType, typing.Union):
        arms = [arm for arm in typing.get_args(annotation) if arm is not type(None)]
        return _coerce(value, arms[0]) if arms else value
    if annotation is UUID and isinstance(value, str):
        return UUID(value)
    if annotation is datetime and isinstance(value, str):
        parsed = datetime.fromisoformat(value)
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)
    if origin is tuple and isinstance(value, list):
        args = typing.get_args(annotation)
        element = args[0] if args else object
        return tuple(_coerce(item, element) for item in value)
    return value


def to_naive_utc(moment: datetime) -> datetime:
    """SQLite DateTime columns store naive UTC; envelopes carry aware UTC."""
    return moment.astimezone(UTC).replace(tzinfo=None) if moment.tzinfo else moment


def from_naive_utc(moment: datetime) -> datetime:
    return moment.replace(tzinfo=UTC) if moment.tzinfo is None else moment
