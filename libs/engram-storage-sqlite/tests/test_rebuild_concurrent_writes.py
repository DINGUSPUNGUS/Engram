"""P0 regression (PRE-M10 GATE, concurrency finding C1): ``engram rebuild``
run concurrently with an ordinary live write must never silently drop events
from the projection it just rebuilt.

Root cause: ``rebuild_projections`` resets a projection's checkpoint to 0 and
replays the log from the start; ``apply()``'s own crash-recovery idempotency
check (``global_seq <= checkpoint``) treats anything at or below the
checkpoint as already applied. A live writer's *own* ``apply()`` call — the
normal, correct behaviour for an ordinary ``engram add`` running in another
process — can jump the checkpoint ahead of events the in-progress rebuild
hasn't replayed yet, so the rebuild's own idempotency check then silently
skips them, even though ``reset()`` had just deleted their rows. Confirmed
via a deterministic single-process reproduction before this fix landed:
seeding 10 memories, replaying 3 of them, then landing one *new* concurrent
write mid-pass left only 4 of the expected 11 memories projected — with no
error raised anywhere.

The fix makes ``rebuild_projections`` detect the exact moment a projection's
checkpoint lands somewhere other than the envelope it was just told to
apply — the invariant a race-free from-zero replay always holds — and
restart the whole pass. These tests reproduce the race deterministically (no
real threads, no timing flakiness) by wrapping a real ``StateProjection`` and
injecting one genuine concurrent write, through an independent
harness sharing the same engine, at a chosen point mid-replay.
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
from engram_storage_sqlite.maintenance import _MAX_REBUILD_ATTEMPTS, rebuild_projections
from engram_storage_sqlite.projections.state import StateProjection
from engram_storage_sqlite.repositories import SqliteMemoryRepository

USER = Provenance(actor="user", detail="test")


class _Harness:
    """One simulated process: its own command service and state projection,
    wired the same way the CLI/API composition roots wire them, sharing the
    caller-supplied engine — exactly as a second real OS process talking to
    the same SQLite file would."""

    def __init__(self, engine: Engine) -> None:
        kinds = build_kind_registry()
        self.store = SqliteEventStore(engine, build_registry())
        self.state = StateProjection(engine)
        bus = InProcessEventBus()

        def _project(envelope: EventEnvelope) -> None:
            if self.state.handles(envelope.event_type):
                self.state.apply(envelope)

        bus.subscribe(_project)
        self.repository = SqliteMemoryRepository(self.store, kinds)
        self.commands = MemoryCommandService(self.repository, bus, SystemClock(), kinds, self.store)

    def create(self, title: str) -> None:
        self.commands.create_memory(
            CreateMemoryInput(
                kind=MemoryKind.FACT, title=title, content="", attributes={"statement": title}
            ),
            USER,
        )


class _InjectsOneConcurrentWrite:
    """Wraps a real ``StateProjection``; on its ``trigger_at``-th ``apply()``
    call, first performs one genuine concurrent write — through an
    independent ``_Harness`` sharing the same engine — before delegating.
    Deterministically reproduces what a second live process racing a rebuild
    would only sometimes land."""

    def __init__(
        self, inner: StateProjection, concurrent_writer: _Harness, *, trigger_at: int
    ) -> None:
        self._inner = inner
        self._writer = concurrent_writer
        self._trigger_at = trigger_at
        self._calls = 0
        self._fired = False

    @property
    def name(self) -> str:
        return self._inner.name

    def handles(self, event_type: str) -> bool:
        return self._inner.handles(event_type)

    def checkpoint(self) -> int:
        return self._inner.checkpoint()

    def reset(self) -> None:
        self._inner.reset()

    def apply(self, envelope: EventEnvelope) -> None:
        self._calls += 1
        if self._calls == self._trigger_at and not self._fired:
            self._fired = True
            self._writer.create("concurrent-write-mid-rebuild")
        self._inner.apply(envelope)


@pytest.mark.integration
def test_rebuild_no_longer_silently_drops_events_raced_by_a_concurrent_write(
    engine: Engine,
) -> None:
    rebuilder = _Harness(engine)
    for i in range(10):
        rebuilder.create(f"m{i}")
    assert rebuilder.state.checkpoint() == 10

    concurrent_writer = _Harness(engine)  # a second, independent "process"
    racing = _InjectsOneConcurrentWrite(rebuilder.state, concurrent_writer, trigger_at=4)

    replayed = rebuild_projections(rebuilder.store, [racing])

    log_head = rebuilder.store.read_all()[-1].global_seq
    assert log_head == 11  # 10 seeded + 1 concurrent
    assert racing.checkpoint() == log_head
    assert replayed == 11  # the retry's own successful pass replayed every event

    # No memory silently missing from the rebuilt projection.
    from sqlmodel import Session, select

    from engram_storage_sqlite.models import MemoryRecord

    with Session(engine) as session:
        titles = {row.title for row in session.exec(select(MemoryRecord)).all()}
    assert titles == {f"m{i}" for i in range(10)} | {"concurrent-write-mid-rebuild"}


@pytest.mark.integration
def test_rebuild_self_heals_from_a_single_transient_race(engine: Engine) -> None:
    """The common case: one brief overlap, not sustained contention — the
    retry converges on its very next attempt, with no caller-visible error."""
    rebuilder = _Harness(engine)
    for i in range(5):
        rebuilder.create(f"m{i}")

    concurrent_writer = _Harness(engine)
    racing = _InjectsOneConcurrentWrite(rebuilder.state, concurrent_writer, trigger_at=2)

    # Must not raise: the race fires exactly once (`_fired` guards it), so the
    # second attempt inside rebuild_projections' retry loop replays cleanly.
    replayed = rebuild_projections(rebuilder.store, [racing])
    assert replayed == 6


class _AlwaysRacingProjection:
    """Simulates sustained contention: every single apply() call races a
    fresh concurrent write, so no attempt can ever converge."""

    def __init__(self, inner: StateProjection, concurrent_writer: _Harness) -> None:
        self._inner = inner
        self._writer = concurrent_writer
        self._n = 0

    @property
    def name(self) -> str:
        return self._inner.name

    def handles(self, event_type: str) -> bool:
        return self._inner.handles(event_type)

    def checkpoint(self) -> int:
        return self._inner.checkpoint()

    def reset(self) -> None:
        self._inner.reset()

    def apply(self, envelope: EventEnvelope) -> None:
        self._n += 1
        self._writer.create(f"noise-{self._n}")
        self._inner.apply(envelope)


@pytest.mark.integration
def test_rebuild_fails_loudly_rather_than_looping_forever_under_sustained_contention(
    engine: Engine,
) -> None:
    rebuilder = _Harness(engine)
    for i in range(5):
        rebuilder.create(f"m{i}")

    concurrent_writer = _Harness(engine)
    always_racing = _AlwaysRacingProjection(rebuilder.state, concurrent_writer)

    with pytest.raises(StorageError, match="did not complete"):
        rebuild_projections(rebuilder.store, [always_racing])

    # Bounded: exactly _MAX_REBUILD_ATTEMPTS attempts were made, not an
    # infinite retry loop. Each attempt's race is detected on its very first
    # envelope (the injected write always outruns it), so apply() was called
    # — and injected exactly one concurrent write — once per attempt.
    assert always_racing._n == _MAX_REBUILD_ATTEMPTS
