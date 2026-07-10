"""engram-events: the kernel every other engram package builds on.

This package defines *how* events exist — the envelope, the type registry,
serialization, and the bus/store/projection contracts. It knows nothing about
memories, SQLite, git, or HTTP, and it must never import another engram package.
"""

from engram_events.bus import EventBus, EventHandler, InProcessEventBus
from engram_events.envelope import EventEnvelope, Provenance
from engram_events.ids import new_uuid7
from engram_events.projection import Projection
from engram_events.registry import (
    EventRegistry,
    EventTypeAlreadyRegisteredError,
    UnknownEventTypeError,
)
from engram_events.serde import deserialize_payload, serialize_payload
from engram_events.store import EventStore, OptimisticConcurrencyError

__all__ = [
    "EventBus",
    "EventEnvelope",
    "EventHandler",
    "EventRegistry",
    "EventStore",
    "EventTypeAlreadyRegisteredError",
    "InProcessEventBus",
    "OptimisticConcurrencyError",
    "Projection",
    "Provenance",
    "UnknownEventTypeError",
    "deserialize_payload",
    "new_uuid7",
    "serialize_payload",
]
