"""Event store contract.

The store is append-only: no update, no delete, ever. Corrections are new
(compensating) events. The canonical implementation lives in
``engram-storage-sqlite``; this protocol is what everything else depends on.
"""

from collections.abc import Sequence
from typing import Protocol
from uuid import UUID

from engram_events.envelope import EventEnvelope


class OptimisticConcurrencyError(Exception):
    """Raised when an append's expected stream sequence no longer matches.

    Someone else appended to the stream first; the caller must reload the
    aggregate and retry the command against current state.
    """

    def __init__(self, stream_id: UUID, expected_seq: int, actual_seq: int) -> None:
        super().__init__(
            f"stream {stream_id}: expected next seq {expected_seq}, but stream is at {actual_seq}"
        )
        self.stream_id = stream_id
        self.expected_seq = expected_seq
        self.actual_seq = actual_seq


class EventStore(Protocol):
    """Append-only log of event envelopes, totally ordered by ``global_seq``."""

    def append(self, envelopes: Sequence[EventEnvelope]) -> Sequence[EventEnvelope]:
        """Atomically append envelopes and return them with ``global_seq`` assigned.

        Raises:
            OptimisticConcurrencyError: if any envelope's ``stream_seq`` does not
                directly follow the stream's current head.
        """
        ...

    def read_stream(self, stream_id: UUID) -> Sequence[EventEnvelope]:
        """Return every envelope of one stream, ordered by ``stream_seq``."""
        ...

    def read_all(
        self, *, after_global_seq: int = 0, limit: int | None = None
    ) -> Sequence[EventEnvelope]:
        """Return envelopes across all streams, ordered by ``global_seq``."""
        ...
