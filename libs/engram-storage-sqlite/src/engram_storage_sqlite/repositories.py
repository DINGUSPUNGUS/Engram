"""Repository adapters: aggregate-level load/append over the event store.

``load`` = read the stream + ``fold``; ``append`` = delegate to the event store.
Thin by design — aggregate logic stays in engram-core.
"""

from collections.abc import Sequence

from engram_core.domain.errors import NotFoundError
from engram_core.domain.kinds import KindRegistry
from engram_core.domain.memory import Memory
from engram_core.domain.proposal import Proposal
from engram_core.domain.values import MemoryId, ProposalId
from engram_events import EventEnvelope
from engram_storage_sqlite.event_store import SqliteEventStore


class SqliteMemoryRepository:
    """Implements the ``MemoryRepository`` port."""

    def __init__(self, store: SqliteEventStore, kinds: KindRegistry) -> None:
        self._store = store
        self._kinds = kinds

    def load(self, memory_id: MemoryId) -> Memory:
        """Replay one memory stream into current state.

        Raises:
            NotFoundError: empty stream or tombstoned memory.
        """
        envelopes = self._store.read_stream(memory_id)
        if not envelopes:
            raise NotFoundError(f"no such memory: {memory_id}")
        memory = Memory.fold(envelopes, self._kinds)
        if memory.deleted:
            raise NotFoundError(f"memory is deleted: {memory_id}")
        return memory

    def append(self, envelopes: Sequence[EventEnvelope]) -> Sequence[EventEnvelope]:
        return self._store.append(envelopes)


class SqliteProposalRepository:
    """Implements the ``ProposalRepository`` port. Lands with phase 5."""

    def __init__(self, store: SqliteEventStore) -> None:
        self._store = store

    def load(self, proposal_id: ProposalId) -> Proposal:
        raise NotImplementedError

    def append(self, envelopes: Sequence[EventEnvelope]) -> Sequence[EventEnvelope]:
        return self._store.append(envelopes)
