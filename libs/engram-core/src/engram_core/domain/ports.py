"""Ports: every dependency the domain/application layers have on the outside world.

Adapters (engram-storage-sqlite, engram-export-git, future plugins) implement these
protocols; the DI wiring in each app decides which implementation is used. Nothing
in engram-core may import an implementation.
"""

from collections.abc import Sequence
from datetime import datetime
from pathlib import Path
from typing import Protocol

from engram_core.application.dto import (
    MemoryQuerySpec,
    MemoryReadModel,
    Page,
    QueryHit,
    TimelineEntry,
)
from engram_core.domain.memory import Memory
from engram_core.domain.proposal import Proposal
from engram_core.domain.values import MemoryId, MemoryKind, ProposalId
from engram_events import EventEnvelope

# ---------------------------------------------------------------------------
# Write side
# ---------------------------------------------------------------------------


class MemoryRepository(Protocol):
    """Load/append access to memory streams (the write side)."""

    def load(self, memory_id: MemoryId) -> Memory:
        """Replay one stream into current state.

        Raises:
            NotFoundError: if the stream does not exist or is tombstoned.
        """
        ...

    def append(self, envelopes: Sequence[EventEnvelope]) -> Sequence[EventEnvelope]:
        """Append new envelopes (optimistic-concurrency-checked via stream_seq).

        Raises:
            StaleVersionError: if the expected stream position was taken.
        """
        ...


class ProposalRepository(Protocol):
    """Load/append access to proposal streams."""

    def load(self, proposal_id: ProposalId) -> Proposal: ...

    def append(self, envelopes: Sequence[EventEnvelope]) -> Sequence[EventEnvelope]: ...


class UnitOfWork(Protocol):
    """Transaction boundary: append + projection updates commit or roll back together."""

    def __enter__(self) -> "UnitOfWork": ...

    def __exit__(self, *exc_info: object) -> None: ...

    def commit(self) -> None: ...

    def rollback(self) -> None: ...


# ---------------------------------------------------------------------------
# Read side (projections)
# ---------------------------------------------------------------------------


class MemoryQuery(Protocol):
    """Query access to the state projection. Never used for writes."""

    def get(self, memory_id: MemoryId) -> MemoryReadModel:
        """Raises NotFoundError if absent, deleted, or not yet projected."""
        ...

    def list_memories(
        self,
        *,
        kind: MemoryKind | None = None,
        tag: str | None = None,
        include_archived: bool = False,
        include_stale: bool = True,
        cursor: str | None = None,
        limit: int = 50,
    ) -> Page[MemoryReadModel]: ...

    def timeline(self, memory_id: MemoryId) -> Sequence[TimelineEntry]:
        """The memory's full event history, oldest first."""
        ...


class QueryEngine(Protocol):
    """Executes a parsed ``MemoryQuerySpec`` against the projections (ADR-0016).

    Full-text match is one operator inside the spec, not a separate capability;
    vector operators arrive behind ``supports_vectors`` (M5) — FTS-only installs
    stay first-class."""

    @property
    def supports_vectors(self) -> bool: ...

    def query(
        self,
        spec: MemoryQuerySpec,
        *,
        cursor: str | None = None,
        limit: int = 20,
    ) -> Page[QueryHit]:
        """AND of every present term; hits carry snippet/score when text matched."""
        ...


class MemoryHistory(Protocol):
    """Time-travel reads: reconstruct a memory as it was (falls out of ADR-0002)."""

    def state_at(
        self,
        memory_id: MemoryId,
        *,
        at: datetime | None = None,
        version: int | None = None,
    ) -> Memory:
        """Fold the stream up to ``at`` (occurred_at <= at) or ``version``.

        Raises:
            NotFoundError: unknown stream, or the memory did not exist yet then.
        """
        ...


class EmbeddingProvider(Protocol):
    """Interface reserved for the embeddings milestone. No implementation exists."""

    @property
    def dimensions(self) -> int: ...

    def embed(self, texts: Sequence[str]) -> Sequence[Sequence[float]]: ...


# ---------------------------------------------------------------------------
# Export / sync side
# ---------------------------------------------------------------------------


class MarkdownSync(Protocol):
    """Boundary to the user-owned markdown+git representation."""

    def export_paths(self) -> Sequence[Path]:
        """Paths currently owned by the exporter (for status/diagnostics)."""
        ...

    def import_external_changes(self) -> Sequence[EventEnvelope]:
        """Diff the export repo against its last exported state and translate
        user edits into ``MemoryEditedExternally`` envelopes (not yet appended)."""
        ...


class VersionControl(Protocol):
    """Thin git facade over the export repository. Wraps GitPython in the adapter.

    Git is a consumer of exported state (ADR-0017): nothing behind this port may
    mutate runtime state."""

    def is_repo(self) -> bool: ...

    def init(self) -> None:
        """Create the repository if absent (idempotent)."""
        ...

    def status(self) -> Sequence[str]:
        """Changed/untracked paths (porcelain-style lines)."""
        ...

    def commit(self, paths: Sequence[Path], message: str) -> str:
        """Stage and commit; returns the commit sha."""
        ...

    def head(self) -> str | None:
        """Current HEAD sha, or None on an empty repository."""
        ...


# ---------------------------------------------------------------------------
# Ambient
# ---------------------------------------------------------------------------


class Clock(Protocol):
    """Injectable time source so domain logic is deterministic under test."""

    def now(self) -> datetime:
        """Timezone-aware UTC now."""
        ...
