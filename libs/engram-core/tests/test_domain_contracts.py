"""Architecture-phase tests: value-object invariants and event registry integrity.

Aggregate behavior tests arrive with the implementations (given events / when
command / then events — see CONTRIBUTING.md).
"""

import dataclasses

import pytest

from engram_core.domain import events as domain_events
from engram_core.domain.errors import ValidationError
from engram_core.domain.values import Slug


@pytest.mark.unit
@pytest.mark.parametrize("valid", ["a", "kahnya-branding", "a1-b2-c3", "x" * 80])
def test_valid_slugs(valid: str) -> None:
    assert str(Slug(valid)) == valid


@pytest.mark.unit
@pytest.mark.parametrize(
    "invalid",
    [
        "",
        "Upper",
        "has space",
        "trailing-",
        "-leading",
        "double--dash",
        "dot.md",
        "../escape",
        "x" * 81,
    ],
)
def test_invalid_slugs_rejected(invalid: str) -> None:
    with pytest.raises(ValidationError):
        Slug(invalid)


@pytest.mark.unit
def test_registry_covers_every_event_dataclass() -> None:
    """Every frozen dataclass in domain.events must be registered — an event type
    that can be emitted but not deserialized would corrupt replay."""
    registry = domain_events.build_registry()
    registered = set(registry.registered_types())
    declared = {
        name
        for name, obj in vars(domain_events).items()
        if isinstance(obj, type) and dataclasses.is_dataclass(obj) and not name.startswith("_")
    }
    assert registered == declared


@pytest.mark.unit
def test_registry_round_trips_a_created_event() -> None:
    from engram_events import deserialize_payload, new_uuid7, serialize_payload

    registry = domain_events.build_registry()
    payload = domain_events.MemoryCreated(
        memory_id=new_uuid7(),
        slug="example",
        title="Example",
        content="body",
        memory_type="fact",
        tags=("a", "b"),
    )
    data = serialize_payload(payload)
    # UUIDs survive asdict as UUID objects; the store adapter owns JSON encoding.
    restored = deserialize_payload(registry, "MemoryCreated", data, schema_version=1)
    assert restored == dataclasses.replace(payload, tags=tuple(data["tags"]))
