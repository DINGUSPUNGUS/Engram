"""Read-side adapter: implements the ``MemoryQuery`` port over projection tables.

Derived values (effective confidence, staleness) are computed here from the stored
signals and the scoring constants — never stored (ADR-0009).
"""

import json
import math
from collections.abc import Sequence
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy.engine import Engine
from sqlalchemy.exc import SQLAlchemyError
from sqlmodel import Session, col, select

from engram_core.application.dto import (
    EvidenceView,
    LinkView,
    MemoryReadModel,
    Page,
    TimelineEntry,
)
from engram_core.domain import scoring
from engram_core.domain.errors import NotFoundError, StorageError
from engram_core.domain.values import MemoryId, MemoryKind
from engram_storage_sqlite.codec import decode_provenance, from_naive_utc
from engram_storage_sqlite.models import (
    EventRecord,
    EvidenceRecord,
    LinkRecord,
    MemoryRecord,
    MemoryTagRecord,
)

_SECONDS_PER_DAY = 86_400.0


def effective_confidence(
    confidence: float,
    kind: MemoryKind,
    anchor: datetime,
    now: datetime,
    config: scoring.ScoringConfig,
) -> float:
    """c_eff = c * 2^(-days_since_anchor / half_life_days) (memory-model.md §5)."""
    days = max((now - anchor).total_seconds() / _SECONDS_PER_DAY, 0.0)
    return confidence * math.pow(2.0, -days / config.half_life_days[kind])


class SqliteMemoryQuery:
    """Queries ``memories``/``memory_tags``/``links``/``evidence`` and, for
    timelines, ``events``."""

    def __init__(self, engine: Engine, config: scoring.ScoringConfig | None = None) -> None:
        self._engine = engine
        self._config = config or scoring.ScoringConfig()

    def get(self, memory_id: MemoryId) -> MemoryReadModel:
        with self._session() as session:
            record = session.get(MemoryRecord, str(memory_id))
            if record is None:
                raise NotFoundError(f"no such memory: {memory_id}")
            return self._read_model(session, record)

    def list_memories(
        self,
        *,
        kind: MemoryKind | None = None,
        tag: str | None = None,
        include_archived: bool = False,
        include_stale: bool = True,
        cursor: str | None = None,
        limit: int = 50,
    ) -> Page[MemoryReadModel]:
        statement = select(MemoryRecord).order_by(col(MemoryRecord.id)).limit(limit + 1)
        if kind is not None:
            statement = statement.where(MemoryRecord.kind == kind.value)
        if not include_archived:
            statement = statement.where(MemoryRecord.archived == False)  # noqa: E712
        if tag is not None:
            statement = statement.join(
                MemoryTagRecord, col(MemoryTagRecord.memory_id) == col(MemoryRecord.id)
            ).where(MemoryTagRecord.tag == tag.strip().lower())
        if cursor is not None:
            statement = statement.where(col(MemoryRecord.id) > cursor)

        with self._session() as session:
            records = session.exec(statement).all()
            has_more = len(records) > limit
            models = [self._read_model(session, record) for record in records[:limit]]
        if not include_stale:
            models = [model for model in models if not model.stale]
        next_cursor = str(records[limit - 1].id) if has_more else None
        return Page(items=tuple(models), next_cursor=next_cursor)

    def timeline(self, memory_id: MemoryId) -> Sequence[TimelineEntry]:
        with self._session() as session:
            rows = session.exec(
                select(EventRecord)
                .where(EventRecord.stream_id == str(memory_id))
                .order_by(col(EventRecord.stream_seq))
            ).all()
        if not rows:
            raise NotFoundError(f"no such memory: {memory_id}")
        return tuple(
            TimelineEntry(
                event_id=UUID(row.event_id),
                event_type=row.event_type,
                occurred_at=from_naive_utc(row.occurred_at),
                actor=decode_provenance(row.provenance).actor,
                stream_seq=row.stream_seq,
            )
            for row in rows
        )

    # -- helpers ------------------------------------------------------------------

    def _session(self) -> Session:
        try:
            return Session(self._engine)
        except SQLAlchemyError as exc:  # pragma: no cover - construction rarely fails
            raise StorageError(f"cannot open session: {exc}") from exc

    def _read_model(self, session: Session, record: MemoryRecord) -> MemoryReadModel:
        kind = MemoryKind(record.kind)
        tags = tuple(
            sorted(
                session.exec(
                    select(MemoryTagRecord.tag).where(MemoryTagRecord.memory_id == record.id)
                ).all()
            )
        )
        links = tuple(
            LinkView(target_id=UUID(row.target_id), relation=row.relation)
            for row in session.exec(
                select(LinkRecord).where(LinkRecord.source_id == record.id)
            ).all()
        )
        evidence = tuple(
            EvidenceView(
                evidence_type=row.evidence_type,
                value=row.value,
                note=row.note,
                added_at=from_naive_utc(row.added_at),
                actor=row.actor,
            )
            for row in session.exec(
                select(EvidenceRecord)
                .where(EvidenceRecord.memory_id == record.id)
                .order_by(col(EvidenceRecord.seq))
            ).all()
        )
        now = datetime.now(UTC)
        anchor = from_naive_utc(record.last_confirmed_at or record.created_at)
        c_eff = effective_confidence(record.confidence, kind, anchor, now, self._config)
        attributes: dict[str, object] = json.loads(record.attributes)
        return MemoryReadModel(
            id=MemoryId(UUID(record.id)),
            kind=kind,
            slug=record.slug,
            title=record.title,
            content=record.content,
            attributes=attributes,
            tags=tags,
            links=links,
            evidence=evidence,
            confidence=record.confidence,
            effective_confidence=c_eff,
            stale=c_eff < self._config.staleness_threshold[kind],
            last_confirmed_at=(
                from_naive_utc(record.last_confirmed_at) if record.last_confirmed_at else None
            ),
            lifetime_policy=record.lifetime_policy,
            lifetime_until=(
                from_naive_utc(record.lifetime_until) if record.lifetime_until else None
            ),
            visibility=record.visibility,
            pinned=record.pinned,
            user_weight=record.user_weight,
            archived=record.archived,
            created_by=record.created_by,
            created_at=from_naive_utc(record.created_at),
            updated_at=from_naive_utc(record.updated_at),
            version=record.version,
        )
