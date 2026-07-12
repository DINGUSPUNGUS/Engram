"""SQLite implementation of the ``EventStore`` protocol.

Appends run in one transaction; the ``uq_events_stream_position`` constraint is the
optimistic-concurrency check, translated to ``OptimisticConcurrencyError`` (never a
leaked ``IntegrityError``). Connections run in WAL mode. Payload/provenance
encoding lives in :mod:`engram_storage_sqlite.codec`.
"""

import dataclasses
from collections.abc import Sequence
from uuid import UUID

from sqlalchemy import event as sa_event
from sqlalchemy.engine import Engine
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlmodel import Session, col, create_engine, func, select

from engram_core.domain.errors import StorageError
from engram_events import EventEnvelope, EventRegistry, OptimisticConcurrencyError
from engram_storage_sqlite.codec import (
    decode_payload,
    decode_provenance,
    encode_payload,
    encode_provenance,
    from_naive_utc,
    to_naive_utc,
)
from engram_storage_sqlite.models import EventRecord


def create_sqlite_engine(url: str) -> Engine:
    """Engine factory: WAL mode + enforced foreign keys on every connection."""
    engine = create_engine(url)

    @sa_event.listens_for(engine, "connect")
    def _configure(dbapi_connection: object, _record: object) -> None:
        cursor = dbapi_connection.cursor()  # type: ignore[attr-defined]
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    return engine


class SqliteEventStore:
    """Append-only event log over the ``events`` table."""

    def __init__(self, engine: Engine, registry: EventRegistry) -> None:
        self._engine = engine
        self._registry = registry

    def append(self, envelopes: Sequence[EventEnvelope]) -> Sequence[EventEnvelope]:
        """Atomically append; returns envelopes with ``global_seq`` assigned.

        Raises:
            OptimisticConcurrencyError: a stream position was already taken.
            StorageError: any other integrity or I/O failure.
        """
        if not envelopes:
            return ()
        records = [
            EventRecord(
                event_id=str(envelope.event_id),
                stream_id=str(envelope.stream_id),
                stream_seq=envelope.stream_seq,
                event_type=envelope.event_type,
                schema_version=envelope.schema_version,
                payload=encode_payload(envelope.payload),
                occurred_at=to_naive_utc(envelope.occurred_at),
                provenance=encode_provenance(envelope.provenance),
            )
            for envelope in envelopes
        ]
        try:
            with Session(self._engine) as session:
                session.add_all(records)
                session.commit()
                for record in records:
                    session.refresh(record)
        except IntegrityError as exc:
            if "uq_events_stream_position" in str(exc.orig) or "stream_seq" in str(exc.orig):
                first = envelopes[0]
                raise OptimisticConcurrencyError(
                    first.stream_id, first.stream_seq, self._stream_head(first.stream_id)
                ) from exc
            raise StorageError(f"event append failed: {exc.orig}") from exc
        except SQLAlchemyError as exc:
            raise StorageError(f"event append failed: {exc}") from exc

        return tuple(
            dataclasses.replace(envelope, global_seq=record.global_seq)
            for envelope, record in zip(envelopes, records, strict=True)
        )

    def read_stream(self, stream_id: UUID) -> Sequence[EventEnvelope]:
        statement = (
            select(EventRecord)
            .where(EventRecord.stream_id == str(stream_id))
            .order_by(col(EventRecord.stream_seq))
        )
        return self._fetch(statement)

    def read_all(
        self, *, after_global_seq: int = 0, limit: int | None = None
    ) -> Sequence[EventEnvelope]:
        statement = (
            select(EventRecord)
            .where(col(EventRecord.global_seq) > after_global_seq)
            .order_by(col(EventRecord.global_seq))
        )
        if limit is not None:
            statement = statement.limit(limit)
        return self._fetch(statement)

    def _fetch(self, statement: object) -> tuple[EventEnvelope, ...]:
        try:
            with Session(self._engine) as session:
                records = session.exec(statement).all()  # type: ignore[call-overload]
        except SQLAlchemyError as exc:
            raise StorageError(f"event read failed: {exc}") from exc
        return tuple(self._to_envelope(record) for record in records)

    def _to_envelope(self, record: EventRecord) -> EventEnvelope:
        return EventEnvelope(
            event_id=UUID(record.event_id),
            stream_id=UUID(record.stream_id),
            stream_seq=record.stream_seq,
            event_type=record.event_type,
            schema_version=self._registry.current_version(record.event_type),
            payload=decode_payload(
                self._registry,
                record.event_type,
                record.payload,
                schema_version=record.schema_version,
            ),
            occurred_at=from_naive_utc(record.occurred_at),
            provenance=decode_provenance(record.provenance),
            global_seq=record.global_seq,
        )

    def _stream_head(self, stream_id: UUID) -> int:
        with Session(self._engine) as session:
            head = session.exec(
                select(func.max(EventRecord.stream_seq)).where(
                    EventRecord.stream_id == str(stream_id)
                )
            ).one()
        return int(head) if head is not None else 0
