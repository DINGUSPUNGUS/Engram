"""The event envelope: the one shape every state change travels in."""

from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID


@dataclass(frozen=True, slots=True)
class Provenance:
    """Who or what caused an event.

    Attributes:
        actor: originator, e.g. ``"user"``, ``"claude"``, ``"chatgpt"``, ``"system"``.
        session_id: opaque conversation/session identifier, if known.
        detail: free-form context (client name, tool name, …).
    """

    actor: str
    session_id: str | None = None
    detail: str | None = None


@dataclass(frozen=True, slots=True)
class EventEnvelope:
    """Immutable wrapper around a domain event payload.

    Attributes:
        event_id: globally unique UUIDv7 of this event.
        stream_id: identity of the aggregate this event belongs to (e.g. a memory).
        stream_seq: 1-based position within the stream. Doubles as the optimistic
            concurrency token: appends declare the ``stream_seq`` they expect next.
        event_type: registered type name, e.g. ``"MemoryCreated"``.
        schema_version: version of the payload schema; upcasters migrate older
            versions at read time so old logs replay forever.
        payload: the registered domain event dataclass instance.
        occurred_at: UTC timestamp of when the change happened.
        provenance: who/what caused it — the audit trail is the log itself.
        global_seq: total order across all streams. Assigned by the event store on
            append; ``None`` until persisted.
    """

    event_id: UUID
    stream_id: UUID
    stream_seq: int
    event_type: str
    schema_version: int
    payload: Any
    occurred_at: datetime
    provenance: Provenance
    global_seq: int | None = None
