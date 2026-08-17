"""Rebuild: replay the whole log through projections (the disposability contract).

``engram rebuild`` and the replay-determinism tests both come through here.
"""

import tempfile
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from engram_core.domain.errors import StorageError
from engram_events import Projection
from engram_storage_sqlite.event_store import SqliteEventStore, create_sqlite_engine
from engram_storage_sqlite.migrate import upgrade_to_head
from engram_storage_sqlite.projections.state import StateProjection

_BATCH_SIZE = 500
_MAX_REBUILD_ATTEMPTS = 3


class _RebuildRace(Exception):
    """Internal only — never escapes ``rebuild_projections``. Signals that a
    projection's checkpoint moved out from under this rebuild pass; the pass
    is unsound past that point and must restart from a fresh ``reset()``."""


def rebuild_projections(store: SqliteEventStore, projections: Sequence[Projection]) -> int:
    """Reset every projection, then replay the full log from global_seq 0.

    Returns the number of envelopes replayed.

    A rebuild pass assumes it is the only writer touching each projection's
    checkpoint while it replays: it zeroes the checkpoint in ``reset()``, then
    walks the log from the start, and ``apply()``'s own crash-recovery
    idempotency check (``global_seq <= checkpoint``) treats any envelope at or
    below the checkpoint as already applied. If a *live* writer commits an
    ordinary event while a rebuild is mid-pass — `engram rebuild` running
    concurrently with `engram add`/the API server, a realistic scenario, not
    a contrived one — that write's own ``apply()`` jumps the checkpoint ahead
    to its own (much higher) global_seq. Every subsequent envelope this
    rebuild pass tries to replay then satisfies ``global_seq <= checkpoint``
    and is silently skipped, even though ``reset()`` had just deleted its row
    moments before: a permanently wrong, half-populated projection that
    ``engram status`` (checkpoint-only drift detection) cannot see, since the
    checkpoint itself is fully caught up — only the expensive differential
    ``status --verify`` catches it. Confirmed via a deterministic
    single-process reproduction (PRE-M10 GATE finding, concurrency P0).

    Rather than giving every ``Projection`` implementation a shared
    cross-process lock — a real change to the port every adapter implements,
    not a contained one — this detects the exact moment a pass becomes
    unsound (a projection's checkpoint isn't left at precisely the envelope
    just handed to it, or ``apply()`` itself failed to insert a row a
    concurrent writer already durably committed) and restarts the whole pass
    from ``reset()``. Bounded:
    if the checkpoint keeps moving because writes are continuous rather than
    transient, this fails loudly with an actionable error instead of quietly
    returning a wrong result. Costs one extra ``checkpoint()`` read per
    envelope per projection versus the previous version — real, but paid
    only by this already-documented-as-slow maintenance path
    (docs/performance.md), never by any per-event write.
    """
    last_race: _RebuildRace | None = None
    for _attempt in range(_MAX_REBUILD_ATTEMPTS):
        try:
            return _rebuild_pass(store, projections)
        except _RebuildRace as race:
            last_race = race
    raise StorageError(
        f"engram rebuild did not complete after {_MAX_REBUILD_ATTEMPTS} attempts:"
        f" {last_race}. Another process kept writing to this space throughout —"
        " stop other `engram`/API activity against it and retry `engram rebuild`."
    )


def _rebuild_pass(store: SqliteEventStore, projections: Sequence[Projection]) -> int:
    for projection in projections:
        projection.reset()
    replayed = 0
    after = 0
    while True:
        batch = store.read_all(after_global_seq=after, limit=_BATCH_SIZE)
        if not batch:
            return replayed
        for envelope in batch:
            assert envelope.global_seq is not None  # persisted envelopes always have one
            for projection in projections:
                if projection.handles(envelope.event_type):
                    try:
                        projection.apply(envelope)
                    except StorageError:
                        # apply() itself failed -- most often a live writer's
                        # *own* apply() of this exact envelope already landed
                        # (row + checkpoint) between this rebuild pass reading
                        # the batch and reaching it, so our own insert collides
                        # on the same UNIQUE slug/PK the two share, because
                        # it's the same row. That is the identical
                        # rebuild/live-write overlap the checkpoint-drift check
                        # below exists for, just caught one step earlier (the
                        # INSERT itself, not the post-apply checkpoint read) --
                        # confirmed via real-thread reproduction (deterministic
                        # single-process tests fully serialize the concurrent
                        # write, so they can only ever land on the drift check,
                        # never this narrower window).
                        #
                        # The checkpoint is the one signal this whole mechanism
                        # already trusts, so use it here too rather than
                        # guessing from the exception: if it has reached (or
                        # passed) this envelope, whatever we just hit is
                        # provably a duplicate of work already durably done,
                        # safe to retry. If it hasn't, the failure is real —
                        # e.g. two *different* events sharing an explicit slug
                        # (MemoryCommandService.create_memory already documents
                        # that as a plain StorageError, no concurrency
                        # involved) — and retrying would only burn attempts
                        # before failing anyway with a misleading "another
                        # process kept writing" message. Re-raise unchanged.
                        if projection.checkpoint() < envelope.global_seq:
                            raise
                        raise _RebuildRace(
                            f"{projection.name} already had global_seq"
                            f" {envelope.global_seq} applied by a concurrent"
                            " writer when this rebuild pass tried to apply it too"
                        ) from None
                    landed = projection.checkpoint()
                    if landed != envelope.global_seq:
                        raise _RebuildRace(
                            f"{projection.name} checkpoint at {landed}, expected"
                            f" exactly {envelope.global_seq} right after replaying"
                            " it — a concurrent write advanced it mid-rebuild"
                        )
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
