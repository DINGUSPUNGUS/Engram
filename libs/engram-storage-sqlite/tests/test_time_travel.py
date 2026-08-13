"""Time travel (M2): fold the stream up to a version or instant — including for
memories that no longer exist. The debugging companion to the timeline."""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.engine import Engine

from engram_core.application.commands.memory_commands import MemoryCommandService
from engram_core.application.dto import CreateMemoryInput, EditMemoryInput
from engram_core.application.queries.history_queries import HistoryQueryService
from engram_core.domain.errors import NotFoundError, ValidationError
from engram_core.domain.events import build_registry
from engram_core.domain.kinds import build_kind_registry
from engram_core.domain.values import MemoryId, MemoryKind
from engram_events import InProcessEventBus, Provenance, SystemClock
from engram_storage_sqlite.event_store import SqliteEventStore
from engram_storage_sqlite.repositories import SqliteMemoryRepository

USER = Provenance(actor="user", detail="test")


@pytest.fixture
def rig(engine: Engine) -> tuple[MemoryCommandService, HistoryQueryService, MemoryId]:
    kinds = build_kind_registry()
    store = SqliteEventStore(engine, build_registry())
    repository = SqliteMemoryRepository(store, kinds)
    commands = MemoryCommandService(repository, InProcessEventBus(), SystemClock(), kinds, store)
    history = HistoryQueryService(repository)
    memory_id = commands.create_memory(
        CreateMemoryInput(
            kind=MemoryKind.FACT,
            title="original title",
            content="v1 content",
            attributes={"statement": "original"},
            tags=("first",),
        ),
        USER,
    )
    commands.edit_memory(memory_id, EditMemoryInput(expected_version=1, title="edited title"), USER)
    commands.tag_memory(memory_id, add=("second",), remove=("first",), provenance=USER)
    return commands, history, memory_id


@pytest.mark.integration
def test_state_at_version_reconstructs_each_step(
    rig: tuple[MemoryCommandService, HistoryQueryService, MemoryId],
) -> None:
    _, history, memory_id = rig

    v1 = history.state_at(memory_id, version=1)
    assert v1.title == "original title"
    assert v1.tags == ("first",)
    assert v1.version == 1

    v2 = history.state_at(memory_id, version=2)
    assert v2.title == "edited title"
    assert v2.tags == ("first",)

    v3 = history.state_at(memory_id, version=3)
    assert v3.tags == ("second",)
    # Asking beyond the head folds everything that exists — same as current state.
    assert history.state_at(memory_id, version=99).version == 3


@pytest.mark.integration
def test_state_at_instant_and_deleted_memories_remain_inspectable(
    rig: tuple[MemoryCommandService, HistoryQueryService, MemoryId],
) -> None:
    commands, history, memory_id = rig
    commands.delete_memory(memory_id, "cleanup", USER)

    # Current-state reads refuse tombstones; time travel does not.
    snapshot = history.state_at(memory_id, at=datetime.now(UTC))
    assert snapshot.deleted is True
    before_delete = history.state_at(memory_id, version=3)
    assert before_delete.deleted is False
    assert before_delete.title == "edited title"

    with pytest.raises(NotFoundError, match="did not exist yet"):
        history.state_at(memory_id, at=datetime.now(UTC) - timedelta(days=1))


@pytest.mark.integration
def test_exactly_one_selector_required(
    rig: tuple[MemoryCommandService, HistoryQueryService, MemoryId],
) -> None:
    _, history, memory_id = rig
    with pytest.raises(ValidationError, match="exactly one"):
        history.state_at(memory_id)
    with pytest.raises(ValidationError, match="exactly one"):
        history.state_at(memory_id, at=datetime.now(UTC), version=1)
