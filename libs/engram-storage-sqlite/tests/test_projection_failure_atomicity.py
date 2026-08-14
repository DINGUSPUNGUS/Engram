"""P1 regression: projection failure atomicity.

The finding under audit: if event N is accepted, projection A applies it,
projection B raises, does B's checkpoint advance anyway (a phantom checkpoint
that implies work which never happened)? Does A's already-committed work get
silently lost? Is the failure visible, and is there a recovery path?

The architecture turns out to already satisfy the required invariant —
``StateProjection.apply`` commits a projection's own row mutations and its own
checkpoint advance in a *single* SQLAlchemy transaction (state.py), and the bus
fan-out (``runtime.py``'s ``_project``) never catches a projection's exception,
so a failing projection's checkpoint cannot advance and a succeeding sibling's
checkpoint is never rolled back for another projection's failure. This test
proves that with a real command service + real event store + real
``StateProjection``, plus one deliberately-failing projection double — not a
redesign, a verification.
"""

import pytest
from sqlalchemy.engine import Engine

from engram_core.application.commands.memory_commands import MemoryCommandService
from engram_core.application.dto import CreateMemoryInput
from engram_core.domain.errors import StorageError
from engram_core.domain.events import build_registry
from engram_core.domain.kinds import build_kind_registry
from engram_core.domain.values import MemoryKind
from engram_events import EventEnvelope, InProcessEventBus, Provenance, SystemClock
from engram_storage_sqlite.event_store import SqliteEventStore
from engram_storage_sqlite.projections.state import StateProjection
from engram_storage_sqlite.queries import SqliteMemoryQuery
from engram_storage_sqlite.repositories import SqliteMemoryRepository

USER = Provenance(actor="user", detail="test")


class _FlakyProjection:
    """A minimal ``Projection`` double that fails to apply one chosen
    ``global_seq``, then behaves normally. Isolates the fan-out invariant
    (siblings unaffected, no phantom checkpoint, recoverable from the log)
    from the real projections' own table-level mechanics, which
    ``test_replay_determinism.py`` already covers."""

    def __init__(self, name: str, fail_at_global_seq: int | None) -> None:
        self._name = name
        self._fail_at = fail_at_global_seq
        self._checkpoint = 0
        self.applied: list[int] = []

    @property
    def name(self) -> str:
        return self._name

    def handles(self, event_type: str) -> bool:
        return True

    def apply(self, envelope: EventEnvelope) -> None:
        assert envelope.global_seq is not None
        if envelope.global_seq <= self._checkpoint:
            return  # idempotent replay / crash recovery, same contract as StateProjection
        if envelope.global_seq == self._fail_at:
            raise StorageError(f"{self._name}: simulated failure at seq {envelope.global_seq}")
        self._checkpoint = envelope.global_seq
        self.applied.append(envelope.global_seq)

    def checkpoint(self) -> int:
        return self._checkpoint

    def reset(self) -> None:
        self._checkpoint = 0
        self.applied = []


class _Harness:
    """``runtime.py``'s fan-out shape: the bus delivers each envelope to every
    projection in order, unguarded — exactly what's under test."""

    def __init__(self, engine: Engine, flaky: _FlakyProjection) -> None:
        kinds = build_kind_registry()
        self.store = SqliteEventStore(engine, build_registry())
        self.state = StateProjection(engine)
        self.flaky = flaky
        self.projections: tuple[object, ...] = (self.state, self.flaky)
        bus = InProcessEventBus()

        def _project(envelope: EventEnvelope) -> None:
            for projection in self.projections:
                if projection.handles(envelope.event_type):  # type: ignore[attr-defined]
                    projection.apply(envelope)  # type: ignore[attr-defined]

        bus.subscribe(_project)
        self.bus = bus
        self.repository = SqliteMemoryRepository(self.store, kinds)
        self.commands = MemoryCommandService(self.repository, bus, SystemClock(), kinds, self.store)
        self.query = SqliteMemoryQuery(engine)


@pytest.mark.integration
def test_failing_projection_leaves_no_phantom_checkpoint_and_does_not_block_siblings(
    engine: Engine,
) -> None:
    flaky = _FlakyProjection("flaky", fail_at_global_seq=2)
    harness = _Harness(engine, flaky)

    # Event 1: both projections succeed.
    memory_id = harness.commands.create_memory(
        CreateMemoryInput(
            kind=MemoryKind.FACT, title="t", content="", attributes={"statement": "t"}
        ),
        USER,
    )
    assert harness.state.checkpoint() == 1
    assert flaky.checkpoint() == 1

    # Event 2: state succeeds, flaky raises. The exception must propagate —
    # never be swallowed — so the caller learns the write is not fully
    # projected, even though it is durably in the log.
    with pytest.raises(StorageError, match="simulated failure at seq 2"):
        harness.commands.tag_memory(memory_id, add=("late",), remove=(), provenance=USER)

    # The event is durably in the log regardless of the projection failure —
    # the log, not any projection, is the source of truth.
    stream = harness.store.read_stream(memory_id)
    assert [e.stream_seq for e in stream] == [1, 2]

    # State (which ran first and succeeded) is NOT rolled back just because a
    # later sibling failed — no distributed transaction ties them together,
    # and none should.
    assert harness.state.checkpoint() == 2
    assert harness.query.get(memory_id).tags == ("late",)

    # flaky's checkpoint did NOT advance: it must never claim to have applied
    # an event it didn't. This is the invariant under audit.
    assert flaky.checkpoint() == 1
    assert flaky.applied == [1]

    # Drift is visible via exactly the mechanism space_status/`/stats` uses:
    # lag = head_global_seq - checkpoint.
    head = stream[-1].global_seq
    assert head is not None
    assert head - harness.state.checkpoint() == 0  # state: caught up
    assert head - flaky.checkpoint() == 1  # flaky: one event behind, correctly reported

    # Recovery: replaying from flaky's own checkpoint (the same technique
    # `engram rebuild` uses, scoped to one projection) catches it up without
    # touching the projections that were never behind. (Simulates the
    # operator having fixed whatever made it fail — the transient fault
    # itself, not the recovery mechanism, is what's being retried here.)
    flaky._fail_at = None
    for envelope in harness.store.read_all(after_global_seq=flaky.checkpoint()):
        flaky.apply(envelope)
    assert flaky.checkpoint() == 2
    assert flaky.applied == [1, 2]

    # Idempotent redelivery: re-applying an already-applied envelope (state
    # replaying event 2 again, as a crash-recovery restart or a second
    # `engram rebuild` would) is a safe no-op, not a double-application.
    harness.state.apply(stream[-1])
    assert harness.state.checkpoint() == 2
    assert harness.query.get(memory_id).tags == ("late",)
