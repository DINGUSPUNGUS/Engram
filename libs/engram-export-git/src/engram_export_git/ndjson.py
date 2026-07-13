"""NDJSON serialization: one JSON object per line, stable keys, stable ordering.

Two record types, each carrying its own ``record_schema_version`` so foreign
consumers (and future engrams) can dispatch without sniffing:

- **event records** (``timeline/events.ndjson``) — the full envelope, ordered by
  ``global_seq``. This is the machine-replayable log: the restore path.
- **memory records** (``metadata/memories.ndjson``) — current-state objects,
  ordered by ``id``. This is the bulk-interchange face for other systems.

All JSON is emitted with sorted keys and compact separators; values use the
kernel's canonical encodings (UUID → str, datetime → ISO-8601 ``Z``).
"""

import json
from datetime import datetime
from typing import Any
from uuid import UUID

from engram_core.application.dto import MemoryReadModel
from engram_core.domain.errors import ValidationError
from engram_events import (
    EventEnvelope,
    EventRegistry,
    Provenance,
    deserialize_payload_json,
    serialize_payload_json,
)
from engram_events.serde import encode_json_value

EVENT_RECORD_SCHEMA_VERSION = 1
MEMORY_RECORD_SCHEMA_VERSION = 1


def dumps(record: dict[str, Any]) -> str:
    """One canonical NDJSON line (no trailing newline)."""
    return json.dumps(record, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def envelope_to_record(envelope: EventEnvelope) -> dict[str, Any]:
    return {
        "record_schema_version": EVENT_RECORD_SCHEMA_VERSION,
        "global_seq": envelope.global_seq,
        "event_id": str(envelope.event_id),
        "stream_id": str(envelope.stream_id),
        "stream_seq": envelope.stream_seq,
        "event_type": envelope.event_type,
        "schema_version": envelope.schema_version,
        "occurred_at": encode_json_value(envelope.occurred_at),
        "provenance": {
            "actor": envelope.provenance.actor,
            "session_id": envelope.provenance.session_id,
            "detail": envelope.provenance.detail,
        },
        "payload": serialize_payload_json(envelope.payload),
    }


def record_to_envelope(registry: EventRegistry, record: dict[str, Any]) -> EventEnvelope:
    """Parse and type-check one event record back into a typed envelope.

    Raises:
        ValidationError: missing fields, bad UUIDs/timestamps, unknown event type,
            or an unsupported record schema version.
    """
    version = record.get("record_schema_version")
    if version != EVENT_RECORD_SCHEMA_VERSION:
        raise ValidationError(f"unsupported event record schema version: {version!r}")
    try:
        provenance = record["provenance"]
        payload = deserialize_payload_json(
            registry,
            record["event_type"],
            record["payload"],
            schema_version=int(record["schema_version"]),
        )
        return EventEnvelope(
            event_id=UUID(record["event_id"]),
            stream_id=UUID(record["stream_id"]),
            stream_seq=int(record["stream_seq"]),
            event_type=str(record["event_type"]),
            schema_version=int(record["schema_version"]),
            payload=payload,
            occurred_at=datetime.fromisoformat(str(record["occurred_at"]).replace("Z", "+00:00")),
            provenance=Provenance(
                actor=str(provenance["actor"]),
                session_id=provenance.get("session_id"),
                detail=provenance.get("detail"),
            ),
            global_seq=int(record["global_seq"]) if record.get("global_seq") is not None else None,
        )
    except ValidationError:
        raise
    except (KeyError, TypeError, ValueError) as exc:
        raise ValidationError(f"malformed event record: {exc!r}") from exc


def memory_to_record(memory: MemoryReadModel) -> dict[str, Any]:
    """Current-state memory object for bulk interchange (derived scores excluded —
    they are functions of *now*, ADR-0009)."""
    return {
        "record_schema_version": MEMORY_RECORD_SCHEMA_VERSION,
        "id": str(memory.id),
        "kind": memory.kind.value,
        "schema_version": 1,
        "title": memory.title,
        "slug": memory.slug,
        "content": memory.content,
        "attributes": encode_json_value(memory.attributes),
        "tags": sorted(memory.tags),
        "links": [
            {"relation": link.relation, "target": str(link.target_id)}
            for link in sorted(memory.links, key=lambda edge: (edge.relation, str(edge.target_id)))
        ],
        "evidence": [
            {
                "type": item.evidence_type,
                "value": item.value,
                "note": item.note,
                "added_at": encode_json_value(item.added_at) if item.added_at else None,
                "actor": item.actor,
            }
            for item in memory.evidence
        ],
        "confidence": memory.confidence,
        "visibility": memory.visibility,
        "lifetime": memory.lifetime_policy,
        "lifetime_until": encode_json_value(memory.lifetime_until),
        "archived": memory.archived,
        "pinned": memory.pinned,
        "user_weight": memory.user_weight,
        "created_by": memory.created_by,
        "created_at": encode_json_value(memory.created_at),
        "updated_at": encode_json_value(memory.updated_at),
        "version": memory.version,
    }
