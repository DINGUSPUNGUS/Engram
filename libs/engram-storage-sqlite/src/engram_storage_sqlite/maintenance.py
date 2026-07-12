"""Rebuild: replay the whole log through projections (the disposability contract).

``engram rebuild`` and the replay-determinism tests both come through here.
"""

from collections.abc import Sequence

from engram_events import Projection
from engram_storage_sqlite.event_store import SqliteEventStore

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
