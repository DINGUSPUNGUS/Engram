"""Kernel contract tests: registry round-trips, upcasting, and bus ordering."""

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import pytest

from engram_events import (
    EventEnvelope,
    EventRegistry,
    EventTypeAlreadyRegisteredError,
    InProcessEventBus,
    Provenance,
    deserialize_payload,
    new_uuid7,
    serialize_payload,
)


@dataclass(frozen=True)
class ThingHappened:
    what: str
    times: int


def _registry() -> EventRegistry:
    registry = EventRegistry()
    registry.register("ThingHappened", ThingHappened, schema_version=2)
    registry.register_upcaster(
        "ThingHappened", 1, lambda data: {**data, "times": data.get("times", 1)}
    )
    return registry


@pytest.mark.unit
def test_payload_round_trip() -> None:
    registry = _registry()
    payload = ThingHappened(what="tested", times=3)
    data = serialize_payload(payload)
    restored = deserialize_payload(registry, "ThingHappened", data, schema_version=2)
    assert restored == payload


@pytest.mark.unit
def test_upcaster_migrates_old_versions() -> None:
    registry = _registry()
    v1_data: dict[str, Any] = {"what": "legacy"}
    restored = deserialize_payload(registry, "ThingHappened", v1_data, schema_version=1)
    assert restored == ThingHappened(what="legacy", times=1)


@pytest.mark.unit
def test_duplicate_registration_rejected() -> None:
    registry = _registry()
    with pytest.raises(EventTypeAlreadyRegisteredError):
        registry.register("ThingHappened", ThingHappened)


@pytest.mark.unit
def test_bus_delivers_in_order_to_all_subscribers() -> None:
    bus = InProcessEventBus()
    seen_a: list[int] = []
    seen_b: list[int] = []
    bus.subscribe(lambda env: seen_a.append(env.stream_seq))
    bus.subscribe(lambda env: seen_b.append(env.stream_seq))

    stream_id = new_uuid7()
    envelopes = [
        EventEnvelope(
            event_id=new_uuid7(),
            stream_id=stream_id,
            stream_seq=seq,
            event_type="ThingHappened",
            schema_version=2,
            payload=ThingHappened(what="x", times=seq),
            occurred_at=datetime.now(UTC),
            provenance=Provenance(actor="test"),
        )
        for seq in (1, 2, 3)
    ]
    bus.publish(envelopes)
    assert seen_a == [1, 2, 3]
    assert seen_b == [1, 2, 3]
