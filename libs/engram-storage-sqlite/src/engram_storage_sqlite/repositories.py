"""Repository adapters: aggregate-level load/append over the event store.

``load`` = read the stream + ``fold``; ``append`` = delegate to the event store.
Thin by design — aggregate logic stays in engram-core. Stubs.
"""

from collections.abc import Sequence

from engram_core.domain.memory import Memory
from engram_core.domain.proposal import Proposal
from engram_core.domain.values import MemoryId, ProposalId
from engram_events import EventEnvelope
from engram_storage_sqlite.event_store import SqliteEventStore


class SqliteMemoryRepository:
    """Implements the ``MemoryRepository`` port."""

    def __init__(self, store: SqliteEventStore) -> None:
        self._store = store

    def load(self, memory_id: MemoryId) -> Memory:
        """Replay one memory stream into current state.

        Raises:
            NotFoundError: empty stream or tombstoned memory.
        """
        raise NotImplementedError

    def append(self, envelopes: Sequence[EventEnvelope]) -> Sequence[EventEnvelope]:
        raise NotImplementedError


class SqliteProposalRepository:
    """Implements the ``ProposalRepository`` port."""

    def __init__(self, store: SqliteEventStore) -> None:
        self._store = store

    def load(self, proposal_id: ProposalId) -> Proposal:
        raise NotImplementedError

    def append(self, envelopes: Sequence[EventEnvelope]) -> Sequence[EventEnvelope]:
        raise NotImplementedError
