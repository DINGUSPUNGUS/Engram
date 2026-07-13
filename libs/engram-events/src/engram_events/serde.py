"""Payload (de)serialization.

Payloads are flat dataclasses; the wire format is JSON-compatible dicts. Reads go
through the registry's upcasters first, so any historical schema version can always
be deserialized into the *current* payload dataclass.

Two levels exist:

- ``serialize_payload``/``deserialize_payload`` — dict form; values keep their
  Python types (UUID, datetime). Used in-process.
- ``serialize_payload_json``/``deserialize_payload_json`` — fully JSON-safe form
  (UUID → str, datetime → ISO-8601 UTC ``Z``, tuples → lists) and the typed
  inverse driven by the payload dataclass's type hints. Every serializer that
  leaves the process (SQLite event store, NDJSON export) must round-trip payloads
  *typed-equal*, so the coercion lives here in the kernel, once.
"""

import dataclasses
import types
import typing
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from engram_events.registry import EventRegistry


def serialize_payload(payload: Any) -> dict[str, Any]:
    """Convert a registered payload dataclass instance to a dict (Python values)."""
    if not dataclasses.is_dataclass(payload) or isinstance(payload, type):
        raise TypeError(f"payload must be a dataclass instance, got {type(payload)!r}")
    return dataclasses.asdict(payload)


def deserialize_payload(
    registry: EventRegistry,
    event_type: str,
    data: dict[str, Any],
    *,
    schema_version: int,
) -> Any:
    """Rehydrate a payload dict (of any historical version) into the current dataclass."""
    migrated = registry.upcast(event_type, dict(data), schema_version)
    payload_type = registry.payload_type(event_type)
    return payload_type(**migrated)


# ---------------------------------------------------------------------------
# JSON-safe form
# ---------------------------------------------------------------------------


def encode_json_value(value: Any) -> Any:
    """Recursively convert a payload value into a JSON-representable one."""
    match value:
        case UUID():
            return str(value)
        case datetime():
            aware = value if value.tzinfo is not None else value.replace(tzinfo=UTC)
            return aware.astimezone(UTC).isoformat().replace("+00:00", "Z")
        case dict():
            return {str(key): encode_json_value(item) for key, item in value.items()}
        case list() | tuple():
            return [encode_json_value(item) for item in value]
        case _:
            return value


def serialize_payload_json(payload: Any) -> dict[str, Any]:
    """Dataclass instance → fully JSON-safe dict (stable value encodings)."""
    return {key: encode_json_value(item) for key, item in serialize_payload(payload).items()}


def deserialize_payload_json(
    registry: EventRegistry,
    event_type: str,
    data: dict[str, Any],
    *,
    schema_version: int,
) -> Any:
    """JSON-safe dict (any historical version) → current, *typed* payload instance."""
    migrated = registry.upcast(event_type, dict(data), schema_version)
    payload_type = registry.payload_type(event_type)
    hints = typing.get_type_hints(payload_type)
    coerced = {
        key: _coerce(value, hints[key]) if key in hints else value
        for key, value in migrated.items()
    }
    return payload_type(**coerced)


def _coerce(value: Any, annotation: Any) -> Any:
    """Drive JSON values back into the annotated Python types."""
    if value is None:
        return None
    origin = typing.get_origin(annotation)
    if origin in (typing.Union, types.UnionType):
        for arm in typing.get_args(annotation):
            if arm is type(None):
                continue
            return _coerce(value, arm)
        return value
    if annotation is UUID and isinstance(value, str):
        return UUID(value)
    if annotation is datetime and isinstance(value, str):
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    if origin is tuple:
        args = typing.get_args(annotation)
        item_annotation = args[0] if args else Any
        return tuple(_coerce(item, item_annotation) for item in value)
    if origin is list:
        args = typing.get_args(annotation)
        item_annotation = args[0] if args else Any
        return [_coerce(item, item_annotation) for item in value]
    return value
