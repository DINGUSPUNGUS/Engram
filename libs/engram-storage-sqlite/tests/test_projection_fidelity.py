"""P1 regression: projection drift detection (status.py's checkpoint lag)
proves a projection is caught up with the log; it cannot prove the state it
computed while catching up is *correct*. ``verify_projection_fidelity`` closes
that blind spot with a differential rebuild: replay the same log into a fresh
copy of the projection and compare content fingerprints.

Not a second, independently-drifting source of truth — both sides run the
identical ``StateProjection`` code against the identical event log; the
scratch copy this creates is discarded immediately after each check.
"""

import dataclasses

import pytest
from sqlalchemy.engine import Engine

from engram_core.application.commands.memory_commands import MemoryCommandService
from engram_core.application.dto import CreateMemoryInput
from engram_core.domain.events import MemoryTagged, build_registry
from engram_core.domain.kinds import build_kind_registry
from engram_core.domain.values import MemoryKind
from engram_events import EventEnvelope, InProcessEventBus, Provenance, SystemClock
from engram_storage_sqlite.event_store import SqliteEventStore
from engram_storage_sqlite.maintenance import verify_projection_fidelity
from engram_storage_sqlite.projections.state import StateProjection
from engram_storage_sqlite.repositories import SqliteMemoryRepository

USER = Provenance(actor="user", detail="test")


class _BuggyStateProjection(StateProjection):
    """A deliberately incorrect projection: tag *removals* are silently
    dropped (a realistic class of merge-logic bug), but checkpoint advancement
    is untouched — it still reaches the same checkpoint as a correct replay,
    at lag 0, forever. This is exactly the case lag-based drift detection
    (status.py) cannot see."""

    def _apply_event(self, session: object, envelope: EventEnvelope) -> None:
        payload = envelope.payload
        if isinstance(payload, MemoryTagged) and payload.removed:
            broken = dataclasses.replace(payload, removed=())
            envelope = dataclasses.replace(envelope, payload=broken)
        super()._apply_event(session, envelope)  # type: ignore[arg-type]


def _harness(
    engine: Engine, state: StateProjection
) -> tuple[MemoryCommandService, SqliteEventStore]:
    kinds = build_kind_registry()
    store = SqliteEventStore(engine, build_registry())
    bus = InProcessEventBus()

    def _project(envelope: EventEnvelope) -> None:
        if state.handles(envelope.event_type):
            state.apply(envelope)

    bus.subscribe(_project)
    repository = SqliteMemoryRepository(store, kinds)
    commands = MemoryCommandService(repository, bus, SystemClock(), kinds, store)
    return commands, store


@pytest.mark.integration
def test_healthy_projection_is_comparable_and_matches_a_rebuild(engine: Engine) -> None:
    state = StateProjection(engine)
    commands, store = _harness(engine, state)
    memory_id = commands.create_memory(
        CreateMemoryInput(
            kind=MemoryKind.FACT, title="t", content="", attributes={"statement": "t"}
        ),
        USER,
    )
    commands.tag_memory(memory_id, add=("a", "b"), remove=(), provenance=USER)

    report = verify_projection_fidelity(store, state)

    assert report.comparable
    assert not report.logic_bug_detected
    assert report.live_fingerprint == report.rebuilt_fingerprint
    assert report.live_checkpoint == report.rebuilt_checkpoint == 2


@pytest.mark.integration
def test_content_bug_is_detected_even_though_checkpoint_lag_is_zero(engine: Engine) -> None:
    """The proof: a buggy live projection reaches the correct checkpoint (lag
    0 — status.py would report it healthy) but computes the wrong content.
    ``verify_projection_fidelity`` catches it; lag alone cannot."""
    buggy = _BuggyStateProjection(engine)
    commands, store = _harness(engine, buggy)
    memory_id = commands.create_memory(
        CreateMemoryInput(
            kind=MemoryKind.FACT, title="t", content="", attributes={"statement": "t"}
        ),
        USER,
    )
    commands.tag_memory(memory_id, add=("a", "b"), remove=(), provenance=USER)
    commands.tag_memory(memory_id, add=(), remove=("a",), provenance=USER)  # the bug drops this

    log_head = store.read_all()[-1].global_seq

    # Lag-based detection alone: fully caught up, reports healthy.
    assert buggy.checkpoint() == log_head

    report = verify_projection_fidelity(store, buggy)

    assert report.comparable  # same checkpoint, so the comparison is meaningful
    assert report.logic_bug_detected  # and it still disagrees with a correct rebuild
    assert report.live_fingerprint != report.rebuilt_fingerprint
