"""Memory aggregate behavior: given events → when command → then events.

The house style for all event-sourced code (CONTRIBUTING.md).
"""

from datetime import UTC, datetime
from typing import Any

import pytest

from engram_core.domain import events as ev
from engram_core.domain.errors import ConflictError, ValidationError
from engram_core.domain.kinds import (
    FactAttributes,
    ProjectAttributes,
    ProjectStatus,
    build_kind_registry,
)
from engram_core.domain.memory import Memory
from engram_core.domain.values import MemoryKind, Slug, new_memory_id
from engram_events import EventEnvelope, Provenance, new_uuid7

KINDS = build_kind_registry()
NOW = datetime(2026, 7, 12, 12, 0, 0, tzinfo=UTC)


def envelope(stream_id: Any, seq: int, payload: object) -> EventEnvelope:
    return EventEnvelope(
        event_id=new_uuid7(),
        stream_id=stream_id,
        stream_seq=seq,
        event_type=type(payload).__name__,
        schema_version=1,
        payload=payload,
        occurred_at=NOW,
        provenance=Provenance(actor="user"),
    )


def created_memory(**overrides: Any) -> Memory:
    memory_id = new_memory_id()
    payloads = Memory.decide_create(
        memory_id,
        MemoryKind.PROJECT,
        Slug("engram-project"),
        "engram",
        "the memory engine",
        ProjectAttributes(name="engram", status=ProjectStatus.ACTIVE),
        KINDS,
        tags=("OSS", "oss", "  Infra  "),
        confidence=0.9,
        **overrides,
    )
    return Memory.fold([envelope(memory_id, 1, payloads[0])], KINDS)


@pytest.mark.unit
def test_create_then_fold_round_trips_state() -> None:
    memory = created_memory()
    assert memory.kind is MemoryKind.PROJECT
    assert str(memory.slug) == "engram-project"
    assert memory.attributes == ProjectAttributes(name="engram", status=ProjectStatus.ACTIVE)
    assert memory.tags == frozenset({"oss", "infra"})  # normalized, deduplicated
    assert memory.confidence == 0.9
    assert memory.version == 1
    assert not memory.archived and not memory.deleted


@pytest.mark.unit
def test_create_rejects_bad_input() -> None:
    memory_id = new_memory_id()
    with pytest.raises(ValidationError):
        Memory.decide_create(
            memory_id,
            MemoryKind.PROJECT,
            Slug("x"),
            "   ",
            "",
            ProjectAttributes(name="x", status=ProjectStatus.IDEA),
            KINDS,
        )
    with pytest.raises(ValidationError):  # wrong attributes type for the kind
        Memory.decide_create(
            memory_id,
            MemoryKind.PROJECT,
            Slug("x"),
            "t",
            "",
            FactAttributes(statement="not a project"),
            KINDS,
        )
    with pytest.raises(ValidationError):
        Memory.decide_create(
            memory_id,
            MemoryKind.PROJECT,
            Slug("x"),
            "t",
            "",
            ProjectAttributes(name="x", status=ProjectStatus.IDEA),
            KINDS,
            confidence=1.5,
        )


@pytest.mark.unit
def test_edit_emits_only_changed_fields_and_noop_emits_nothing() -> None:
    memory = created_memory()
    assert memory.decide_edit(title="engram", content="the memory engine") == ()

    payloads = memory.decide_edit(title="engram v2")
    assert payloads == (ev.MemoryEdited(title="engram v2", content=None, slug=None),)

    evolved = memory.evolve(envelope(memory.id, 2, payloads[0]))
    assert evolved.title == "engram v2"
    assert evolved.content == "the memory engine"  # untouched
    assert evolved.version == 2


@pytest.mark.unit
def test_tagging_normalizes_and_drops_noops() -> None:
    memory = created_memory()
    assert memory.decide_tag(add=("oss",)) == ()  # already present
    assert memory.decide_tag(remove=("nonexistent",)) == ()

    payloads = memory.decide_tag(add=("Python ",), remove=("infra",))
    assert payloads == (ev.MemoryTagged(added=("python",), removed=("infra",)),)
    evolved = memory.evolve(envelope(memory.id, 2, payloads[0]))
    assert evolved.tags == frozenset({"oss", "python"})


@pytest.mark.unit
def test_lifecycle_guards() -> None:
    memory = created_memory()
    archived = memory.evolve(envelope(memory.id, 2, memory.decide_archive("noise")[0]))
    assert archived.archived

    with pytest.raises(ConflictError):
        archived.decide_archive()  # already archived
    with pytest.raises(ConflictError):
        archived.decide_edit(title="nope")  # archived memories are read-only

    restored = archived.evolve(envelope(memory.id, 3, archived.decide_restore()[0]))
    assert not restored.archived
    with pytest.raises(ConflictError):
        restored.decide_restore()  # not archived

    deleted = restored.evolve(envelope(memory.id, 4, restored.decide_delete()[0]))
    assert deleted.deleted
    with pytest.raises(ConflictError):
        deleted.decide_delete()
    with pytest.raises(ConflictError):
        deleted.decide_record_access()


@pytest.mark.unit
def test_access_feeds_importance_signals() -> None:
    memory = created_memory()
    once = memory.evolve(envelope(memory.id, 2, memory.decide_record_access("recall")[0]))
    twice = once.evolve(envelope(memory.id, 3, once.decide_record_access()[0]))
    assert twice.importance.access_count == 2
    assert twice.importance.last_accessed_at == NOW
    assert twice.version == 3


@pytest.mark.unit
def test_fold_rejects_malformed_streams() -> None:
    with pytest.raises(ValidationError):
        Memory.fold([], KINDS)
    memory = created_memory()
    with pytest.raises(ValidationError):  # stream must start with MemoryCreated
        Memory.fold([envelope(memory.id, 1, ev.MemoryEdited(title="x"))], KINDS)
    with pytest.raises(ValidationError):  # future-phase event types must not fold silently
        memory.evolve(envelope(memory.id, 2, ev.MemoryConfirmed()))
