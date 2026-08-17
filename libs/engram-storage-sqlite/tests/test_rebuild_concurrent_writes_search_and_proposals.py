"""PRE-M10 follow-up (concurrency P0, second instance of the class closed for
``StateProjection``): ``SearchProjection`` and ``ProposalProjection`` shared the
exact same checkpoint contract as ``StateProjection`` -- same ``apply()`` shape,
same fan-out from ``InProcessEventBus.publish``, same participation in every real
``rebuild_projections`` call (see ``apps/cli``/``apps/api`` composition roots) --
but, until this fix, still advanced their checkpoint with an unconditional
``checkpoint.last_global_seq = envelope.global_seq; session.add(...)`` write
instead of ``StateProjection``'s compare-and-swap. That let a rebuild pass's own
sequential commits silently regress the checkpoint back down after an
independent concurrent writer had already advanced it past an envelope the
rebuild hadn't reached yet -- erasing the record that envelope's work already
landed, so the rebuild's own forward walk re-applied it when it got there.

Unlike ``test_rebuild_concurrent_writes.py``'s
``test_rebuild_never_silently_double_applies_under_a_checkpoint_regression`` --
which lets its two writers race "freely" and only wins the exact interleaving
some fraction of runs (documented there as 5/8) -- these tests force the race
deterministically: ``_checkpoint_row`` is the one helper identical across the
pre-fix and post-fix source (its shape never changed), so patching it to pause
*after* the rebuild's own stale read of the checkpoint for global_seq 2, and
resuming only once a second, independent projection instance has fully
committed global_seq 6 in between, reproduces the exact stale-read/late-commit
window every single run -- no scheduler luck, no sleeps.

The probe events (``MemoryTagged``, ``ProposalApproved``) are plain "recompute
from current state" UPDATEs with no UNIQUE constraint to catch a double-apply
-- and, unlike ``MemoryAccessed``'s ``access_count += 1``, applying the exact
same envelope's payload twice in a row happens to leave the *field values*
identical (a set, not a delta) -- so the reliable oracle here isn't "did the
data end up wrong", it's "did the rebuild's own instance apply this envelope's
mutation more than once despite reporting success". That is precisely the
invariant the checkpoint is supposed to make impossible, and precisely what a
future non-idempotent event on either projection (a counter, a running total)
would turn into the same silent corruption ``MemoryAccessed`` produced.
"""

import threading
from uuid import UUID, uuid4

import pytest
from sqlalchemy.engine import Engine
from sqlmodel import Session

from engram_core.application.commands.memory_commands import MemoryCommandService
from engram_core.application.commands.proposal_commands import ProposalCommandService
from engram_core.application.dto import CreateMemoryInput
from engram_core.domain.errors import StorageError
from engram_core.domain.events import build_registry
from engram_core.domain.kinds import build_kind_registry
from engram_core.domain.values import MemoryId, MemoryKind, ProposalId
from engram_events import EventEnvelope, InProcessEventBus, Provenance, SystemClock
from engram_storage_sqlite.event_store import SqliteEventStore
from engram_storage_sqlite.maintenance import rebuild_projections
from engram_storage_sqlite.models import ProjectionCheckpointRecord
from engram_storage_sqlite.projections.proposals import ProposalProjection
from engram_storage_sqlite.projections.search import SearchProjection
from engram_storage_sqlite.repositories import SqliteMemoryRepository, SqliteProposalRepository

USER = Provenance(actor="user", detail="test")


def _confirm_draft(memory_id: UUID) -> dict[str, object]:
    """A minimal, valid v2 draft. ``open_proposal`` only wire-validates drafts
    -- it never touches the referenced memory -- so an unrelated random id is
    fine; this proposal is never merged."""
    return {
        "draft_schema_version": 2,
        "op": "confirm_memory",
        "memory_id": str(memory_id),
        "base_version": 0,
        "note": None,
    }


# ---------------------------------------------------------------------------
# search
# ---------------------------------------------------------------------------


class _SearchHarness:
    """One simulated process: its own command service and search projection,
    wired the same way the CLI/API composition roots wire them, sharing the
    caller-supplied engine."""

    def __init__(self, engine: Engine) -> None:
        kinds = build_kind_registry()
        self.store = SqliteEventStore(engine, build_registry())
        self.search = SearchProjection(engine)
        bus = InProcessEventBus()

        def _project(envelope: EventEnvelope) -> None:
            if self.search.handles(envelope.event_type):
                self.search.apply(envelope)

        bus.subscribe(_project)
        self.repository = SqliteMemoryRepository(self.store, kinds)
        self.commands = MemoryCommandService(self.repository, bus, SystemClock(), kinds, self.store)

    def create(self, title: str) -> MemoryId:
        return self.commands.create_memory(
            CreateMemoryInput(
                kind=MemoryKind.FACT, title=title, content="", attributes={"statement": title}
            ),
            USER,
        )


@pytest.mark.integration
def test_rebuild_never_silently_double_applies_search_projection_under_a_checkpoint_regression(
    engine: Engine,
) -> None:
    rebuilder = _SearchHarness(engine)
    ids = [rebuilder.create(f"m{i}") for i in range(5)]
    assert rebuilder.search.checkpoint() == 5
    m0_id = ids[0]

    # Append the 6th event -- MemoryTagged on an *existing* row, not an
    # insert, so a double-apply trips no UNIQUE constraint -- through a
    # second, independent command service wired to a subscriber-less bus, so
    # it lands durably in the log without SearchProjection having applied it
    # yet.
    kinds = build_kind_registry()
    silent_commands = MemoryCommandService(
        SqliteMemoryRepository(rebuilder.store, kinds),
        InProcessEventBus(),  # nobody subscribed -- append only, no apply
        SystemClock(),
        kinds,
        rebuilder.store,
    )
    silent_commands.tag_memory(m0_id, add=("probe-tag",), provenance=USER)
    envelope_6 = rebuilder.store.read_all(after_global_seq=5)[0]
    assert envelope_6.event_type == "MemoryTagged"
    assert envelope_6.global_seq == 6

    m0_recreated = threading.Event()
    barrier = threading.Barrier(2)
    fired = {"paused": False}
    current_seq: dict[str, int | None] = {"value": None}
    real_apply = SearchProjection.apply
    real_apply_event = SearchProjection._apply_event
    real_checkpoint_row = SearchProjection._checkpoint_row
    real_reset = SearchProjection.reset
    # Applications of global_seq 6's mutation *since the last reset()* --
    # across *both* projection instances (the independent second writer and
    # the rebuild's own). A retry's own reset() legitimately wipes whatever
    # the failed attempt (and anything racing it) had written, so counting
    # raw calls across the whole test would flag a healthy retry as
    # corruption; counting only what survives since the pass that actually
    # committed last reset() is the invariant that matches final state.
    applications_of_6_since_reset = {"count": 0}

    def _tracking_apply(self: SearchProjection, envelope: EventEnvelope) -> None:
        # Records which global_seq the rebuild's own instance is currently
        # inside apply() for, so the (unchanged pre/post-fix) checkpoint
        # read below can find the exact right moment to pause -- without
        # ever seeing the envelope itself.
        is_target = self is rebuilder.search
        if is_target:
            current_seq["value"] = envelope.global_seq
        try:
            real_apply(self, envelope)
        finally:
            if is_target:
                current_seq["value"] = None
        if is_target and envelope.global_seq == 1:
            m0_recreated.set()

    def _counted_apply_event(
        self: SearchProjection, session: Session, envelope: EventEnvelope
    ) -> None:
        if envelope.global_seq == 6:
            applications_of_6_since_reset["count"] += 1
        real_apply_event(self, session, envelope)

    def _counting_reset(self: SearchProjection) -> None:
        real_reset(self)
        if self is rebuilder.search:
            applications_of_6_since_reset["count"] = 0

    def _paused_checkpoint_row(
        self: SearchProjection, session: Session
    ) -> ProjectionCheckpointRecord:
        row = real_checkpoint_row(self, session)
        if self is rebuilder.search and current_seq["value"] == 2 and not fired["paused"]:
            fired["paused"] = True
            # The rebuild's own apply(envelope_2) has now read the checkpoint
            # (still at 1) but not yet committed anything for envelope 2.
            # Block right here until the second, independent writer's own
            # apply(envelope_6) has fully committed -- forcing the exact
            # stale-read/late-commit window a compare-and-swap exists to
            # close: this call's own upcoming commit will use the checkpoint
            # value it already read (1), not the value now on disk (6).
            barrier.wait()
        return row

    SearchProjection.apply = _tracking_apply  # type: ignore[method-assign]
    SearchProjection._apply_event = _counted_apply_event  # type: ignore[method-assign]
    SearchProjection._checkpoint_row = _paused_checkpoint_row  # type: ignore[method-assign]
    SearchProjection.reset = _counting_reset  # type: ignore[method-assign]
    results: dict[str, object] = {}

    def run_rebuild() -> None:
        try:
            results["replayed"] = rebuild_projections(rebuilder.store, [rebuilder.search])
        except StorageError as exc:
            results["error"] = exc

    thread = threading.Thread(target=run_rebuild)
    try:
        thread.start()
        assert m0_recreated.wait(timeout=10), "m0 was never recreated by rebuild"
        # A second, independent SearchProjection instance applying envelope 6
        # -- the actual concurrent writer this scenario needs -- while the
        # rebuild thread sits paused, mid-apply(envelope_2), holding a stale
        # (pre-this-commit) checkpoint value. This always succeeds cleanly:
        # nothing else has touched the checkpoint since it read it.
        real_apply(SearchProjection(engine), envelope_6)
        barrier.wait()
        thread.join(timeout=10)
    finally:
        SearchProjection.apply = real_apply  # type: ignore[method-assign]
        SearchProjection._apply_event = real_apply_event  # type: ignore[method-assign]
        SearchProjection._checkpoint_row = real_checkpoint_row  # type: ignore[method-assign]
        SearchProjection.reset = real_reset  # type: ignore[method-assign]

    assert not thread.is_alive(), "rebuild thread hung"

    if "error" in results:
        # A CAS conflict on envelope 2 is expected to be caught by
        # maintenance.py and reclassified (the checkpoint proves envelope
        # 2's *predecessor* work -- envelope 6 -- already landed), retrying
        # the whole pass cleanly. But this test's job is to prove the CAS
        # mechanism itself never lets a *reported success* coincide with
        # wrong data -- not to assume any particular caller-side retry
        # policy. A loud, uncaught failure here is a safe outcome in its own
        # right (nothing was silently duplicated) even if the classification
        # that would otherwise retry it isn't present.
        assert applications_of_6_since_reset["count"] in (0, 1)
        return

    # Reported success: the release-gate invariant demands this be correct,
    # not merely "checkpoint matches the log head".
    assert results["replayed"] == 6
    assert rebuilder.search.checkpoint() == 6
    assert applications_of_6_since_reset["count"] <= 1, (
        "SILENT CORRUPTION: global_seq 6's mutation was applied"
        f" {applications_of_6_since_reset['count']} times since the last reset() but"
        f" rebuild reported success ({results!r}) -- event log correct, projection"
        " double-mutated, status would report healthy"
    )


# ---------------------------------------------------------------------------
# proposals
# ---------------------------------------------------------------------------


class _ProposalHarness:
    """One simulated process: its own command service and proposal projection,
    wired the same way the CLI/API composition roots wire them, sharing the
    caller-supplied engine."""

    def __init__(self, engine: Engine) -> None:
        kinds = build_kind_registry()
        self.store = SqliteEventStore(engine, build_registry())
        self.proposals_projection = ProposalProjection(engine)
        bus = InProcessEventBus()

        def _project(envelope: EventEnvelope) -> None:
            if self.proposals_projection.handles(envelope.event_type):
                self.proposals_projection.apply(envelope)

        bus.subscribe(_project)
        memory_repo = SqliteMemoryRepository(self.store, kinds)
        proposal_repo = SqliteProposalRepository(self.store)
        self.commands = ProposalCommandService(
            proposal_repo, memory_repo, bus, SystemClock(), kinds, self.store
        )

    def open(self, title: str) -> ProposalId:
        return self.commands.open_proposal(title, "", [_confirm_draft(uuid4())], USER)


@pytest.mark.integration
def test_rebuild_never_silently_double_applies_proposal_projection_under_a_checkpoint_regression(
    engine: Engine,
) -> None:
    rebuilder = _ProposalHarness(engine)
    ids = [rebuilder.open(f"p{i}") for i in range(5)]
    assert rebuilder.proposals_projection.checkpoint() == 5
    p0_id = ids[0]

    # Append the 6th event -- ProposalApproved on an *existing* row, not an
    # insert, so a double-apply trips no UNIQUE constraint -- through a
    # second, independent command service wired to a subscriber-less bus, so
    # it lands durably in the log without ProposalProjection having applied
    # it yet.
    kinds = build_kind_registry()
    silent_commands = ProposalCommandService(
        SqliteProposalRepository(rebuilder.store),
        SqliteMemoryRepository(rebuilder.store, kinds),
        InProcessEventBus(),  # nobody subscribed -- append only, no apply
        SystemClock(),
        kinds,
        rebuilder.store,
    )
    silent_commands.approve_proposal(p0_id, None, USER)
    envelope_6 = rebuilder.store.read_all(after_global_seq=5)[0]
    assert envelope_6.event_type == "ProposalApproved"
    assert envelope_6.global_seq == 6

    p0_recreated = threading.Event()
    barrier = threading.Barrier(2)
    fired = {"paused": False}
    current_seq: dict[str, int | None] = {"value": None}
    real_apply = ProposalProjection.apply
    real_apply_event = ProposalProjection._apply_event
    real_checkpoint_row = ProposalProjection._checkpoint_row
    real_reset = ProposalProjection.reset
    # Applications of global_seq 6's mutation *since the last reset()* --
    # across *both* projection instances (the independent second writer and
    # the rebuild's own). A retry's own reset() legitimately wipes whatever
    # the failed attempt (and anything racing it) had written, so counting
    # raw calls across the whole test would flag a healthy retry as
    # corruption; counting only what survives since the pass that actually
    # committed last reset() is the invariant that matches final state.
    applications_of_6_since_reset = {"count": 0}

    def _tracking_apply(self: ProposalProjection, envelope: EventEnvelope) -> None:
        is_target = self is rebuilder.proposals_projection
        if is_target:
            current_seq["value"] = envelope.global_seq
        try:
            real_apply(self, envelope)
        finally:
            if is_target:
                current_seq["value"] = None
        if is_target and envelope.global_seq == 1:
            p0_recreated.set()

    def _counted_apply_event(
        self: ProposalProjection, session: Session, envelope: EventEnvelope
    ) -> None:
        if envelope.global_seq == 6:
            applications_of_6_since_reset["count"] += 1
        real_apply_event(self, session, envelope)

    def _counting_reset(self: ProposalProjection) -> None:
        real_reset(self)
        if self is rebuilder.proposals_projection:
            applications_of_6_since_reset["count"] = 0

    def _paused_checkpoint_row(
        self: ProposalProjection, session: Session
    ) -> ProjectionCheckpointRecord:
        row = real_checkpoint_row(self, session)
        is_target = self is rebuilder.proposals_projection
        if is_target and current_seq["value"] == 2 and not fired["paused"]:
            fired["paused"] = True
            # The rebuild's own apply(envelope_2) has now read the checkpoint
            # (still at 1) but not yet committed anything for envelope 2.
            # Block right here until the second, independent writer's own
            # apply(envelope_6) has fully committed -- forcing the exact
            # stale-read/late-commit window a compare-and-swap exists to
            # close.
            barrier.wait()
        return row

    ProposalProjection.apply = _tracking_apply  # type: ignore[method-assign]
    ProposalProjection._apply_event = _counted_apply_event  # type: ignore[method-assign]
    ProposalProjection._checkpoint_row = _paused_checkpoint_row  # type: ignore[method-assign]
    ProposalProjection.reset = _counting_reset  # type: ignore[method-assign]
    results: dict[str, object] = {}

    def run_rebuild() -> None:
        try:
            results["replayed"] = rebuild_projections(
                rebuilder.store, [rebuilder.proposals_projection]
            )
        except StorageError as exc:
            results["error"] = exc

    thread = threading.Thread(target=run_rebuild)
    try:
        thread.start()
        assert p0_recreated.wait(timeout=10), "p0 was never recreated by rebuild"
        # A second, independent ProposalProjection instance applying envelope
        # 6 -- the actual concurrent writer this scenario needs -- while the
        # rebuild thread sits paused, mid-apply(envelope_2), holding a stale
        # (pre-this-commit) checkpoint value. This always succeeds cleanly:
        # nothing else has touched the checkpoint since it read it.
        real_apply(ProposalProjection(engine), envelope_6)
        barrier.wait()
        thread.join(timeout=10)
    finally:
        ProposalProjection.apply = real_apply  # type: ignore[method-assign]
        ProposalProjection._apply_event = real_apply_event  # type: ignore[method-assign]
        ProposalProjection._checkpoint_row = real_checkpoint_row  # type: ignore[method-assign]
        ProposalProjection.reset = real_reset  # type: ignore[method-assign]

    assert not thread.is_alive(), "rebuild thread hung"

    if "error" in results:
        # A CAS conflict on envelope 2 is expected to be caught by
        # maintenance.py and reclassified (the checkpoint proves envelope
        # 2's *predecessor* work -- envelope 6 -- already landed), retrying
        # the whole pass cleanly. But this test's job is to prove the CAS
        # mechanism itself never lets a *reported success* coincide with
        # wrong data -- not to assume any particular caller-side retry
        # policy. A loud, uncaught failure here is a safe outcome in its own
        # right (nothing was silently duplicated) even if the classification
        # that would otherwise retry it isn't present.
        assert applications_of_6_since_reset["count"] in (0, 1)
        return

    # Reported success: the release-gate invariant demands this be correct,
    # not merely "checkpoint matches the log head".
    assert results["replayed"] == 6
    assert rebuilder.proposals_projection.checkpoint() == 6
    assert applications_of_6_since_reset["count"] <= 1, (
        "SILENT CORRUPTION: global_seq 6's mutation was applied"
        f" {applications_of_6_since_reset['count']} times since the last reset() but"
        f" rebuild reported success ({results!r}) -- event log correct, projection"
        " double-mutated, status would report healthy"
    )
