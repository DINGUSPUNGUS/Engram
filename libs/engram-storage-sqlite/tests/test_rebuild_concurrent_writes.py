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

import contextlib
import threading
from uuid import UUID

import pytest
from sqlalchemy.engine import Engine
from sqlmodel import Session, select

from engram_core.application.commands.memory_commands import MemoryCommandService
from engram_core.application.dto import CreateMemoryInput
from engram_core.domain.errors import StorageError
from engram_core.domain.events import build_registry
from engram_core.domain.kinds import build_kind_registry
from engram_core.domain.values import MemoryKind
from engram_events import EventEnvelope, InProcessEventBus, Provenance, SystemClock
from engram_storage_sqlite.event_store import SqliteEventStore
from engram_storage_sqlite.maintenance import _MAX_REBUILD_ATTEMPTS, rebuild_projections
from engram_storage_sqlite.models import MemoryRecord
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


@pytest.mark.integration
def test_rebuild_recovers_from_a_real_thread_insert_collision(engine: Engine) -> None:
    """Companion to the checkpoint-regression test below, covering the other
    failure shape: an *insert*, not an update. The harness above
    (``_InjectsOneConcurrentWrite``) always lets a concurrent write's own
    ``apply()`` finish, as one atomic unit, before the rebuild reaches the
    same envelope, so it can only ever exercise the checkpoint-*ahead* path
    -- never a case where the rebuild's own INSERT for a ``MemoryCreated``
    is genuinely in flight at the same instant as another writer's INSERT of
    the identical row (same memory_id, same slug). Only real threads,
    racing freely (no barrier gating other than release ordering — the
    exact interleaving varies run to run, which is the point: the checkpoint
    is no longer a reliable stand-in for "has this been applied", so the
    rebuild's own attempt can still land after another writer's), can force
    that window. Confirmed via a dedicated probe during the PRE-M10
    follow-up audit: this used to raise a raw, uncaught IntegrityError-
    derived ``StorageError`` on the rebuild's first attempt (real, though
    never unsafe -- no row was ever lost); ``maintenance.py``'s fix
    reclassifies it as the same retryable race once the checkpoint proves
    the colliding row is already durably, correctly applied.
    """
    rebuilder = _Harness(engine)
    for i in range(5):
        rebuilder.create(f"m{i}")
    assert rebuilder.state.checkpoint() == 5

    kinds = build_kind_registry()
    silent_commands = MemoryCommandService(
        SqliteMemoryRepository(rebuilder.store, kinds),
        InProcessEventBus(),  # nobody subscribed -- append only, no apply
        SystemClock(),
        kinds,
        rebuilder.store,
    )
    silent_commands.create_memory(
        CreateMemoryInput(
            kind=MemoryKind.FACT,
            title="concurrent-write",
            content="",
            attributes={"statement": "concurrent-write"},
        ),
        USER,
    )
    envelope_6 = rebuilder.store.read_all(after_global_seq=5)[0]
    assert envelope_6.global_seq == 6

    barrier = threading.Barrier(2)
    fired = {"once": False}
    real_apply = StateProjection.apply

    def _paused_apply(self: StateProjection, envelope: EventEnvelope) -> None:
        if self is rebuilder.state and envelope.global_seq == 6 and not fired["once"]:
            fired["once"] = True
            barrier.wait()
        real_apply(self, envelope)

    StateProjection.apply = _paused_apply  # type: ignore[method-assign]
    results: dict[str, object] = {}

    def run_rebuild() -> None:
        try:
            results["replayed"] = rebuild_projections(rebuilder.store, [rebuilder.state])
        except StorageError as exc:  # pragma: no cover -- would mean the fix regressed
            results["error"] = exc

    thread = threading.Thread(target=run_rebuild)
    try:
        thread.start()
        # This can itself now race the rebuild's own *ongoing* envelope 1-5
        # progress (state.py's compare-and-swap fix correctly detects that
        # too, a related but different race than the one this test targets)
        # -- an accepted, already-covered outcome here, not a failure of
        # this test.
        with contextlib.suppress(StorageError):
            StateProjection(engine).apply(envelope_6)
        barrier.wait()
        thread.join(timeout=10)
    finally:
        StateProjection.apply = real_apply  # type: ignore[method-assign]

    assert not thread.is_alive(), "rebuild thread hung"
    assert "error" not in results, f"rebuild did not recover: {results.get('error')}"
    assert results["replayed"] == 6
    assert rebuilder.state.checkpoint() == 6

    with Session(engine) as session:
        titles = {row.title for row in session.exec(select(MemoryRecord)).all()}
    assert titles == {f"m{i}" for i in range(5)} | {"concurrent-write"}


@pytest.mark.integration
def test_rebuild_never_silently_double_applies_under_a_checkpoint_regression(
    engine: Engine,
) -> None:
    """PRE-M10 follow-up finding (concurrency P0 -- a second, narrower instance
    of the class the original P0 fix closed one layer up): the harness above
    (``_InjectsOneConcurrentWrite``) always lets a concurrent write's *own*
    ``apply()`` run to full completion, as one atomic unit, before the
    rebuild reaches the same point -- it can only ever exercise the
    checkpoint-*ahead* path (``landed != envelope.global_seq`` catches it
    immediately). It can never express the narrower, only-real-threads-can-
    produce window this test forces: the checkpoint update itself
    (``checkpoint.last_global_seq = envelope.global_seq``) was an
    unconditional overwrite with no compare-and-swap, keyed only by the
    row's primary key. If a concurrent writer's *own* commit (racing ahead,
    to global_seq 6) landed *between* two of the rebuild's own sequential
    per-envelope commits (still working through 1-5), the rebuild's *next*
    commit — for a lower global_seq it was legitimately processing —
    silently regressed the checkpoint back down, erasing the record that 6
    was already applied. The rebuild then reached envelope 6 itself and
    re-applied it. For an event with no UNIQUE constraint at stake
    (``MemoryAccessed``: ``access_count += 1``, not idempotent, not an
    insert), that duplicate application landed with **no error at all**:
    ``rebuild_projections`` returned successfully, and the checkpoint ended
    up matching the log head exactly (what ``engram status`` calls
    healthy) — over a projection that had just silently double-counted an
    access. Confirmed via real-thread reproduction during the PRE-M10
    follow-up audit (5/8 runs corrupted silently, no exception, before the
    fix). The invariant this test actually enforces: whatever the exact
    interleaving, a *reported success* must never coincide with wrong data
    -- a loud failure is an acceptable outcome; silent corruption is not.
    """
    rebuilder = _Harness(engine)
    for i in range(5):
        rebuilder.create(f"m{i}")
    assert rebuilder.state.checkpoint() == 5

    with Session(engine) as session:
        m0 = session.exec(select(MemoryRecord).where(MemoryRecord.title == "m0")).one()
        m0_id = UUID(m0.id)

    # Append the 6th event -- a mutation on an *existing* row, not an insert,
    # so a double-apply trips no UNIQUE constraint and would otherwise be
    # completely silent -- through a second, independent command service
    # wired to a bus with no subscriber, so it lands durably in the log
    # without any projection having applied it yet.
    kinds = build_kind_registry()
    silent_commands = MemoryCommandService(
        SqliteMemoryRepository(rebuilder.store, kinds),
        InProcessEventBus(),  # nobody subscribed -- append only, no apply
        SystemClock(),
        kinds,
        rebuilder.store,
    )
    silent_commands.record_access(m0_id, None, USER)
    envelope_6 = rebuilder.store.read_all(after_global_seq=5)[0]
    assert envelope_6.event_type == "MemoryAccessed"
    assert envelope_6.global_seq == 6

    # Let the concurrent write race freely against the rebuild's *own*
    # envelope 2-5 commits (the actual window the regression needs -- see
    # docstring): only gated on m0 existing again post-``reset()`` (m0 is
    # always envelope 1) and on not overlapping the rebuild's own attempt at
    # envelope 6 itself (a separate, already-covered collision).
    m0_recreated = threading.Event()
    barrier = threading.Barrier(2)
    fired = {"paused": False}
    real_apply = StateProjection.apply

    def _controlled_apply(self: StateProjection, envelope: EventEnvelope) -> None:
        if self is rebuilder.state and envelope.global_seq == 1:
            real_apply(self, envelope)
            m0_recreated.set()
            return
        if self is rebuilder.state and envelope.global_seq == 6 and not fired["paused"]:
            fired["paused"] = True
            barrier.wait()
        real_apply(self, envelope)

    StateProjection.apply = _controlled_apply  # type: ignore[method-assign]
    results: dict[str, object] = {}

    def run_rebuild() -> None:
        try:
            results["replayed"] = rebuild_projections(rebuilder.store, [rebuilder.state])
        except StorageError as exc:
            results["error"] = exc

    thread = threading.Thread(target=run_rebuild)
    try:
        thread.start()
        assert m0_recreated.wait(timeout=10), "m0 was never recreated by rebuild"
        # A second, independent StateProjection instance applying the same
        # envelope the rebuild is concurrently working towards. A
        # correctly-detected conflict here (state.py's compare-and-swap fix)
        # is an accepted outcome -- a loud failure, not silent corruption --
        # so it's swallowed rather than failing the test.
        with contextlib.suppress(StorageError):
            real_apply(StateProjection(engine), envelope_6)
        barrier.wait()
        thread.join(timeout=10)
    finally:
        StateProjection.apply = real_apply  # type: ignore[method-assign]

    assert not thread.is_alive(), "rebuild thread hung"

    with Session(engine) as session:
        m0_after = session.exec(select(MemoryRecord).where(MemoryRecord.id == str(m0_id))).one()

    if "error" in results:
        # Loud and safe: the log is untouched, nothing was silently dropped
        # or duplicated. Not the release-gate violation this test targets.
        assert m0_after.access_count in (0, 1)
        return

    # Reported success: the release-gate invariant demands this be correct,
    # not merely "checkpoint matches the log head".
    assert results["replayed"] == 6
    assert rebuilder.state.checkpoint() == 6
    assert m0_after.access_count == 1, (
        f"SILENT CORRUPTION: access_count={m0_after.access_count} but rebuild"
        f" reported success ({results!r}) -- event log correct, projection"
        " wrong, status would report healthy"
    )
