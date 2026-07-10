"""SQLite implementation of the ``EventStore`` protocol. Architecture-phase stubs.

Implementation notes for the milestone that fills this in:
- appends run in one transaction: insert rows, let SQLite assign ``global_seq``;
  a violated ``uq_events_stream_position`` constraint is translated to
  ``OptimisticConcurrencyError`` (never leaked as ``IntegrityError``),
- payload/provenance JSON encoding handles UUID and datetime,
- connections use WAL mode; multi-process writers are safe, see ADR-0001.
"""

from collections.abc import Sequence
from uuid import UUID

from sqlalchemy.engine import Engine

from engram_events import EventEnvelope, EventRegistry


class SqliteEventStore:
    """Append-only event log over the ``events`` table."""

    def __init__(self, engine: Engine, registry: EventRegistry) -> None:
        self._engine = engine
        self._registry = registry

    def append(self, envelopes: Sequence[EventEnvelope]) -> Sequence[EventEnvelope]:
        """Atomically append; returns envelopes with ``global_seq`` assigned.

        Raises:
            OptimisticConcurrencyError: a stream position was already taken.
            StorageError: I/O or integrity failure unrelated to concurrency.
        """
        raise NotImplementedError

    def read_stream(self, stream_id: UUID) -> Sequence[EventEnvelope]:
        """All envelopes of one stream ordered by ``stream_seq`` (payloads
        deserialized through the registry's upcasters)."""
        raise NotImplementedError

    def read_all(
        self, *, after_global_seq: int = 0, limit: int | None = None
    ) -> Sequence[EventEnvelope]:
        """Envelopes across all streams ordered by ``global_seq``."""
        raise NotImplementedError
