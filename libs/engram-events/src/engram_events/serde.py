"""Payload (de)serialization.

Payloads are flat dataclasses; the wire format is JSON-compatible dicts. Reads go
through the registry's upcasters first, so any historical schema version can always
be deserialized into the *current* payload dataclass.
"""

import dataclasses
from typing import Any

from engram_events.registry import EventRegistry


def serialize_payload(payload: Any) -> dict[str, Any]:
    """Convert a registered payload dataclass instance to a JSON-compatible dict."""
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
