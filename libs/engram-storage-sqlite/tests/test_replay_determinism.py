"""THE M1 invariant: same log ⇒ same projection state, every time.

Drives the full write path (service → aggregate → store → bus → projection), then
resets and replays, and asserts the projected state is identical. If this test
breaks, every rebuildability promise in the architecture is broken.
"""

from collections.abc import Sequence

import pytest
from sqlalchemy.engine import Engine

from engram_core.application.commands.memory_commands import MemoryCommandService
from engram_core.application.dto import (
    CreateMemoryInput,
    EditMemoryInput,
    MemoryReadModel,
)
from engram_core.domain.errors import NotFoundError
from engram_core.domain.events import build_registry
from engram_core.domain.kinds import build_kind_registry
from engram_core.domain.values import MemoryKind
from engram_events import EventEnvelope, InProcessEventBus, Provenance, SystemClock
from engram_storage_sqlite.event_store import SqliteEventStore
from engram_storage_sqlite.maintenance import rebuild_projections
from engram_storage_sqlite.projections.state import StateProjection
from engram_storage_sqlite.queries import SqliteMemoryQuery
from engram_storage_sqlite.repositories import SqliteMemoryRepository

USER = Provenance(actor="user", detail="test")
ASSISTANT = Provenance(actor="claude", session_id="s42")


class _Harness:
    """The CLI runtime's shape, wired for a scratch database."""

    def __init__(self, engine: Engine) -> None:
        kinds = build_kind_registry()
        self.store = SqliteEventStore(engine, build_registry())
        self.state = StateProjection(engine)
        bus = InProcessEventBus()

        def _project(envelope: EventEnvelope) -> None:
            if self.state.handles(envelope.event_type):
                self.state.apply(envelope)

        bus.subscribe(_project)
        self.commands = MemoryCommandService(
            SqliteMemoryRepository(self.store, kinds), bus, SystemClock(), kinds, self.store
        )
        self.query = SqliteMemoryQuery(engine)


def _stable_view(models: Sequence[MemoryReadModel]) -> list[tuple[object, ...]]:
    """Everything the projection stores, excluding query-time derived values."""
    return [
        (
            m.id,
            m.kind,
            m.slug,
            m.title,
            m.content,
            tuple(sorted(m.attributes.items())),
            m.tags,
            m.confidence,
            m.lifetime_policy,
            m.visibility,
            m.archived,
            m.created_at,
            m.updated_at,
            m.version,
        )
        for m in models
    ]


@pytest.mark.integration
def test_full_write_path_then_rebuild_is_deterministic(engine: Engine) -> None:
    harness = _Harness(engine)
    commands, query = harness.commands, harness.query

    project_id = commands.create_memory(
        CreateMemoryInput(
            kind=MemoryKind.PROJECT,
            title="engram",
            content="the memory engine",
            attributes={"name": "engram", "status": "active"},
            tags=("oss",),
        ),
        USER,
    )
    fact_id = commands.create_memory(
        CreateMemoryInput(
            kind=MemoryKind.FACT,
            title="User prefers dark mode",
            content="",
            attributes={"statement": "User prefers dark mode"},
        ),
        ASSISTANT,
    )
    doomed_id = commands.create_memory(
        CreateMemoryInput(
            kind=MemoryKind.FACT,
            title="temp",
            content="",
            attributes={"statement": "temp"},
        ),
        USER,
    )

    project_v1 = query.get(project_id)
    commands.edit_memory(
        project_id,
        EditMemoryInput(expected_version=project_v1.version, title="engram (active)"),
        USER,
    )
    commands.tag_memory(project_id, add=("infra",), remove=("oss",), provenance=USER)
    commands.record_access(project_id, "recall test", ASSISTANT)
    commands.archive_memory(fact_id, "example", USER)
    commands.delete_memory(doomed_id, "never mind", USER)

    # -- state assertions before rebuild ---------------------------------------
    live = query.list_memories(include_archived=True).items
    assert {m.id for m in live} == {project_id, fact_id}  # tombstoned row is gone
    project = query.get(project_id)
    assert project.title == "engram (active)"
    assert project.tags == ("infra",)
    assert project.version == 4  # created, edited, tagged, accessed — per-stream seq
    assert query.get(fact_id).archived
    with pytest.raises(NotFoundError):
        query.get(doomed_id)
    assert query.get(fact_id).confidence == pytest.approx(0.60)  # assistant prior
    assert project.confidence == pytest.approx(0.95)  # user-stated prior

    timeline = query.timeline(project_id)
    assert [e.event_type for e in timeline] == [
        "MemoryCreated",
        "MemoryEdited",
        "MemoryTagged",
        "MemoryAccessed",
    ]
    assert timeline[-1].actor == "claude"

    # -- THE invariant: reset + replay reproduces identical state ---------------
    before = _stable_view(query.list_memories(include_archived=True, limit=200).items)
    checkpoint_before = harness.state.checkpoint()

    replayed = rebuild_projections(harness.store, [harness.state])

    after = _stable_view(query.list_memories(include_archived=True, limit=200).items)
    assert after == before
    assert harness.state.checkpoint() == checkpoint_before
    assert replayed == 8  # 3 creates + edit + tag + access + archive + delete
    # And a second replay is just as deterministic (idempotent reset).
    rebuild_projections(harness.store, [harness.state])
    assert _stable_view(query.list_memories(include_archived=True, limit=200).items) == before
