"""Space health: how far each projection is behind the event log (drift detection).

A projection is *drifted* when its checkpoint trails the log head — e.g. after a
crash between append and apply, or a schema migration that added a projection.
The fix is always the same and always safe: ``engram rebuild``.
"""

from collections.abc import Sequence
from dataclasses import dataclass

from sqlalchemy import func
from sqlalchemy.engine import Engine
from sqlalchemy.exc import SQLAlchemyError
from sqlmodel import Session, select

from engram_core.domain.errors import StorageError
from engram_events import Projection
from engram_storage_sqlite.models import EventRecord, MemoryRecord


@dataclass(frozen=True, slots=True)
class ProjectionHealth:
    name: str
    checkpoint: int
    lag: int  # head_global_seq - checkpoint; 0 = up to date


@dataclass(frozen=True, slots=True)
class SpaceStatus:
    event_count: int
    head_global_seq: int
    memory_count: int
    projections: tuple[ProjectionHealth, ...]

    @property
    def drifted(self) -> bool:
        return any(p.lag > 0 for p in self.projections)


def space_status(engine: Engine, projections: Sequence[Projection]) -> SpaceStatus:
    """Collect log totals and per-projection checkpoints."""
    try:
        with Session(engine) as session:
            head = session.exec(select(func.max(EventRecord.global_seq))).one() or 0
            event_count = session.exec(select(func.count()).select_from(EventRecord)).one()
            memory_count = session.exec(select(func.count()).select_from(MemoryRecord)).one()
    except SQLAlchemyError as exc:
        raise StorageError(f"status read failed: {exc}") from exc
    return SpaceStatus(
        event_count=int(event_count),
        head_global_seq=int(head),
        memory_count=int(memory_count),
        projections=tuple(
            ProjectionHealth(
                name=projection.name,
                checkpoint=(checkpoint := projection.checkpoint()),
                lag=int(head) - checkpoint,
            )
            for projection in projections
        ),
    )
