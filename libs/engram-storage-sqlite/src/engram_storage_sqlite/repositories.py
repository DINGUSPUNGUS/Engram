"""Repository adapters: aggregate-level load/append over the event store.

``load`` = read the stream + ``fold``; ``append`` = delegate to the event store.
Thin by design — aggregate logic stays in engram-core.
"""

from collections.abc import Sequence
from datetime import datetime

from engram_core.domain.errors import NotFoundError
from engram_core.domain.kinds import KindRegistry
from engram_core.domain.memory import Memory
from engram_core.domain.proposal import Proposal
from engram_core.domain.values import MemoryId, ProposalId
from engram_events import EventEnvelope
from engram_storage_sqlite.event_store import SqliteEventStore


class SqliteMemoryRepository:
    """Implements the ``MemoryRepository`` and ``MemoryHistory`` ports."""

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

    def state_at(
        self,
        memory_id: MemoryId,
        *,
        at: datetime | None = None,
        version: int | None = None,
    ) -> Memory:
        """Time travel (ADR-0002): fold the stream, stopping at ``at`` or ``version``.

        Unlike ``load``, tombstoned memories are *not* rejected — inspecting the
        history of a deleted memory is exactly what this read is for.

        Raises:
            NotFoundError: unknown stream, or nothing had happened yet by then.
        """
        envelopes = self._store.read_stream(memory_id)
        if not envelopes:
            raise NotFoundError(f"no such memory: {memory_id}")
        if version is not None:
            selected = [e for e in envelopes if e.stream_seq <= version]
        else:
            assert at is not None  # the application service validates exactly-one
            selected = [e for e in envelopes if e.occurred_at <= at]
        if not selected:
            raise NotFoundError(f"memory {memory_id} did not exist yet at that point")
        return Memory.fold(selected, self._kinds)


class SqliteProposalRepository:
    """Implements the ``ProposalRepository`` port. Lands with M4."""

    def __init__(self, store: SqliteEventStore) -> None:
        self._store = store

    def load(self, proposal_id: ProposalId) -> Proposal:
        raise NotImplementedError

    def append(self, envelopes: Sequence[EventEnvelope]) -> Sequence[EventEnvelope]:
        return self._store.append(envelopes)
