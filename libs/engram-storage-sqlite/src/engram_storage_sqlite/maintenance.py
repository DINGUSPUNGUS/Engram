"""Rebuild: replay the whole log through projections (the disposability contract).

``engram rebuild`` and the replay-determinism tests both come through here.
"""

import tempfile
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from engram_events import Projection
from engram_storage_sqlite.event_store import SqliteEventStore, create_sqlite_engine
from engram_storage_sqlite.migrate import upgrade_to_head
from engram_storage_sqlite.projections.state import StateProjection

_BATCH_SIZE = 500


def rebuild_projections(store: SqliteEventStore, projections: Sequence[Projection]) -> int:
    """Reset every projection, then replay the full log from global_seq 0.

    Returns the number of envelopes replayed.
    """
    for projection in projections:
        projection.reset()
    replayed = 0
    after = 0
    while True:
        batch = store.read_all(after_global_seq=after, limit=_BATCH_SIZE)
        if not batch:
            return replayed
        for envelope in batch:
            for projection in projections:
                if projection.handles(envelope.event_type):
                    projection.apply(envelope)
            replayed += 1
        last_seq = batch[-1].global_seq
        assert last_seq is not None
        after = last_seq


@dataclass(frozen=True, slots=True)
class ProjectionFidelityReport:
    """Live projection vs. one fresh, throwaway full replay of the same log."""

    live_checkpoint: int
    rebuilt_checkpoint: int
    live_fingerprint: str
    rebuilt_fingerprint: str

    @property
    def comparable(self) -> bool:
        """False when the live projection hasn't reached the same checkpoint
        as the rebuild — a fingerprint mismatch there is expected (different
        amount of history applied), not evidence of anything. Use
        ``engram status``/lag first; this check assumes lag is already 0."""
        return self.live_checkpoint == self.rebuilt_checkpoint

    @property
    def logic_bug_detected(self) -> bool:
        """True only when both replayed the identical prefix of the log and
        still disagree on content — the blind spot lag-based drift detection
        (status.py) cannot see: a projection fully caught up (lag 0) that
        computed the *wrong* state."""
        return self.comparable and self.live_fingerprint != self.rebuilt_fingerprint


def verify_projection_fidelity(
    store: SqliteEventStore, live: StateProjection
) -> ProjectionFidelityReport:
    """Differential rebuild check (P1: projection drift detection cannot detect
    projection *logic* bugs). Replays the full log into a fresh, temporary copy
    of the state projection and compares its content fingerprint against the
    live one.

    Not a second source of truth that can itself drift: both fingerprints come
    from the identical projection code reading the identical event log — one
    incrementally, applied as each write happened; one in a single bulk pass,
    right now. A mismatch is the projection's own logic disagreeing with
    itself, not disagreement with an independent oracle — and the scratch copy
    is discarded immediately after, so nothing new is left around to drift.
    """
    live_checkpoint = live.checkpoint()
    live_fingerprint = live.fingerprint()

    with tempfile.TemporaryDirectory(prefix="engram-fidelity-") as tmp_dir:
        scratch_path = Path(tmp_dir) / "scratch.db"
        upgrade_to_head(scratch_path)
        scratch_engine = create_sqlite_engine(f"sqlite:///{scratch_path}")
        try:
            scratch = StateProjection(scratch_engine)
            rebuild_projections(store, [scratch])
            rebuilt_checkpoint = scratch.checkpoint()
            rebuilt_fingerprint = scratch.fingerprint()
        finally:
            scratch_engine.dispose()

    return ProjectionFidelityReport(
        live_checkpoint=live_checkpoint,
        rebuilt_checkpoint=rebuilt_checkpoint,
        live_fingerprint=live_fingerprint,
        rebuilt_fingerprint=rebuilt_fingerprint,
    )
