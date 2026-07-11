"""Architecture-phase tests: value-object invariants, event registry integrity,
and kind-schema registry integrity.

Aggregate behavior tests arrive with the implementations (given events / when
command / then events — see CONTRIBUTING.md).
"""

import dataclasses
from datetime import datetime

import pytest

from engram_core.domain import events as domain_events
from engram_core.domain import scoring
from engram_core.domain.errors import ValidationError
from engram_core.domain.kinds import ProjectAttributes, ProjectStatus, build_kind_registry
from engram_core.domain.values import (
    Lifetime,
    MemoryKind,
    RetentionPolicy,
    Slug,
    validate_confidence,
)


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
        kind="project",
        slug="engram",
        title="engram",
        content="the memory engine itself",
        attributes={"name": "engram", "status": "active"},
        tags=("oss",),
    )
    data = serialize_payload(payload)
    # UUIDs survive asdict as UUID objects; the store adapter owns JSON encoding.
    restored = deserialize_payload(registry, "MemoryCreated", data, schema_version=1)
    assert restored == dataclasses.replace(payload, tags=tuple(data["tags"]))


# -- kind registry (ADR-0008) ---------------------------------------------------


@pytest.mark.unit
def test_kind_registry_covers_all_twelve_kinds() -> None:
    registry = build_kind_registry()
    assert set(registry.registered_kinds()) == set(MemoryKind)


@pytest.mark.unit
def test_kind_registry_parses_valid_attributes() -> None:
    registry = build_kind_registry()
    attributes = registry.parse(
        MemoryKind.PROJECT,
        {"name": "engram", "status": ProjectStatus.ACTIVE},
        schema_version=1,
    )
    assert attributes == ProjectAttributes(name="engram", status=ProjectStatus.ACTIVE)


@pytest.mark.unit
def test_kind_registry_rejects_unknown_fields() -> None:
    registry = build_kind_registry()
    with pytest.raises(ValidationError):
        registry.parse(MemoryKind.FACT, {"statement": "x", "bogus": 1}, schema_version=1)


# -- justification spine ---------------------------------------------------------


@pytest.mark.unit
def test_confidence_bounds() -> None:
    assert validate_confidence(0.0) == 0.0
    assert validate_confidence(1.0) == 1.0
    with pytest.raises(ValidationError):
        validate_confidence(1.01)


@pytest.mark.unit
def test_lifetime_until_invariant() -> None:
    Lifetime(RetentionPolicy.UNTIL, until=datetime(2026, 12, 31))
    with pytest.raises(ValidationError):
        Lifetime(RetentionPolicy.UNTIL)  # 'until' policy requires a date
    with pytest.raises(ValidationError):
        Lifetime(RetentionPolicy.STANDARD, until=datetime(2026, 12, 31))


@pytest.mark.unit
def test_scoring_tables_cover_all_kinds() -> None:
    """Half-life and staleness constants must exist for every kind, or the future
    scoring projection would KeyError on kind #13."""
    assert set(scoring.HALF_LIFE_DAYS) == set(MemoryKind)
    assert set(scoring.STALENESS_THRESHOLD) == set(MemoryKind)
