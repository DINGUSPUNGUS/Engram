"""P0 regression: a genuine optimistic-concurrency race must never escape as a
raw ``OptimisticConcurrencyError`` — only the typed ``StaleVersionError`` the
``MemoryRepository``/``ProposalRepository`` ports document (translated in
``engram_storage_sqlite.repositories``). Covers the application/service
boundary independently of HTTP (the HTTP-level 409/RFC 9457 proof lives in
``apps/api/tests/test_concurrency_conflict_api.py``).
"""

from datetime import UTC, datetime
from uuid import UUID

import pytest
from sqlalchemy.engine import Engine

from engram_core.application.commands.memory_commands import MemoryCommandService
from engram_core.application.dto import CreateMemoryInput
from engram_core.domain.errors import StaleVersionError
from engram_core.domain.events import MemoryArchived, MemoryTagged, build_registry
from engram_core.domain.kinds import build_kind_registry
from engram_core.domain.values import MemoryId, MemoryKind
from engram_events import EventEnvelope, InProcessEventBus, Provenance, SystemClock, new_uuid7
from engram_storage_sqlite.event_store import SqliteEventStore
from engram_storage_sqlite.maintenance import rebuild_projections
from engram_storage_sqlite.projections.state import StateProjection
from engram_storage_sqlite.queries import SqliteMemoryQuery
from engram_storage_sqlite.repositories import SqliteMemoryRepository

USER = Provenance(actor="user", detail="test")


class _Harness:
    """The CLI/API runtime's shape, wired for a scratch database."""

    def __init__(self, engine: Engine) -> None:
        kinds = build_kind_registry()
        self.store = SqliteEventStore(engine, build_registry())
        self.state = StateProjection(engine)
        bus = InProcessEventBus()

        def _project(envelope: EventEnvelope) -> None:
            if self.state.handles(envelope.event_type):
                self.state.apply(envelope)

        bus.subscribe(_project)
        self.bus = bus
        self.repository = SqliteMemoryRepository(self.store, kinds)
        self.commands = MemoryCommandService(self.repository, bus, SystemClock(), kinds, self.store)
        self.query = SqliteMemoryQuery(engine)

    def commit_as_second_writer(self, envelopes: list[EventEnvelope]) -> None:
        """Append and publish, exactly like a concurrent caller's own
        ``MemoryCommandService._commit`` would — not a bare store write."""
        appended = self.repository.append(envelopes)
        self.bus.publish(appended)


def _envelope(stream_id: UUID, seq: int, payload: object) -> EventEnvelope:
    return EventEnvelope(
        event_id=new_uuid7(),
        stream_id=stream_id,
        stream_seq=seq,
        event_type=type(payload).__name__,
        schema_version=1,
        payload=payload,
        occurred_at=datetime(2026, 8, 14, 9, 30, tzinfo=UTC),
        provenance=USER,
    )


def _create(harness: _Harness) -> MemoryId:
    return harness.commands.create_memory(
        CreateMemoryInput(
            kind=MemoryKind.FACT,
            title="temp",
            content="",
            attributes={"statement": "temp"},
        ),
        USER,
    )


@pytest.mark.integration
def test_repository_translates_race_to_stale_version_not_raw_exception(engine: Engine) -> None:
    """Two writers both hold stream position 2: the loser gets ``StaleVersionError``.

    This is the P0 finding's exact defect surface — ``SqliteEventStore.append``
    raises ``engram_events.OptimisticConcurrencyError`` (a plain ``Exception``,
    not an ``EngramError``) on the real unique-constraint violation; the
    repository must translate it before it crosses the port.
    """
    harness = _Harness(engine)
    memory_id = _create(harness)

    # Winner: a genuine second writer takes stream_seq 2 first.
    harness.commit_as_second_writer([_envelope(memory_id, 2, MemoryArchived(reason="winner"))])

    # Loser: computed against the same base version (1) the winner started from.
    with pytest.raises(StaleVersionError):
        harness.repository.append([_envelope(memory_id, 2, MemoryTagged(added=("late",)))])


@pytest.mark.integration
def test_conflicting_multi_event_batch_leaves_no_partial_write(engine: Engine) -> None:
    """A losing batch with more than one envelope must not partially land.

    The loser's batch targets stream_seq 2 (collides with the winner) and 3
    (does not collide). If the append were not atomic, seq 3 could be persisted
    even though seq 2 was rejected — this proves it cannot.
    """
    harness = _Harness(engine)
    memory_id = _create(harness)

    harness.commit_as_second_writer([_envelope(memory_id, 2, MemoryArchived(reason="winner"))])

    loser_batch = [
        _envelope(memory_id, 2, MemoryTagged(added=("x",))),
        _envelope(memory_id, 3, MemoryTagged(added=("y",))),
    ]
    with pytest.raises(StaleVersionError):
        harness.repository.append(loser_batch)

    stream = harness.store.read_stream(memory_id)
    assert [e.stream_seq for e in stream] == [1, 2]  # create + winner only
    assert [e.event_type for e in stream] == ["MemoryCreated", "MemoryArchived"]


@pytest.mark.integration
def test_projection_and_replay_agree_with_the_winner_only(engine: Engine) -> None:
    """After a rejected race, the projection reflects only the winner — and
    rebuilding from the log reproduces exactly that state (replay determinism)."""
    harness = _Harness(engine)
    memory_id = _create(harness)

    harness.commit_as_second_writer([_envelope(memory_id, 2, MemoryArchived(reason="winner"))])
    with pytest.raises(StaleVersionError):
        harness.repository.append([_envelope(memory_id, 2, MemoryTagged(added=("late",)))])

    projected = harness.query.get(memory_id)
    assert projected.version == 2
    assert projected.archived
    assert projected.tags == ()  # the loser's tag never applied

    checkpoint_before = harness.state.checkpoint()
    rebuild_projections(harness.store, [harness.state])
    replayed = harness.query.get(memory_id)

    assert replayed.version == projected.version
    assert replayed.archived == projected.archived
    assert replayed.tags == projected.tags
    assert harness.state.checkpoint() == checkpoint_before
