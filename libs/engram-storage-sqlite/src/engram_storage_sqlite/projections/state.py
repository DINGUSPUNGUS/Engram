"""The state projection: folds memory events into the current-state tables.

Deterministic and idempotent per ``global_seq``: envelopes at or below the
checkpoint are skipped, and row updates plus the checkpoint advance commit in one
transaction — replaying the whole log always lands on the same rows
(the M1 invariant, CI-tested).
"""

import hashlib
import json

from sqlalchemy import func, inspect, update
from sqlalchemy.engine import Engine
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlmodel import Session, col, delete, select

from engram_core.domain import events as ev
from engram_core.domain import scoring
from engram_core.domain.errors import StorageError
from engram_events import EventEnvelope
from engram_storage_sqlite.codec import encode_json, to_naive_utc
from engram_storage_sqlite.models import (
    EvidenceRecord,
    LinkRecord,
    MemoryRecord,
    MemoryTagRecord,
    ProjectionCheckpointRecord,
)

_NAME = "state"


class StateProjection:
    """memories / memory_tags / links / projection_checkpoints."""

    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    @property
    def name(self) -> str:
        return _NAME

    def handles(self, event_type: str) -> bool:
        # Every projection observes every event: the checkpoint tracks the whole
        # log, so unrelated streams (e.g. proposals) never read as drift.
        # Irrelevant events no-op in _apply_event and only advance the checkpoint.
        return True

    def apply(self, envelope: EventEnvelope) -> None:
        if envelope.global_seq is None:
            raise StorageError("cannot project an unpersisted envelope (global_seq is None)")
        try:
            with Session(self._engine) as session:
                checkpoint = self._checkpoint_row(session)
                if envelope.global_seq <= checkpoint.last_global_seq:
                    return  # idempotent replay / crash recovery
                self._apply_event(session, envelope)
                self._advance_checkpoint(session, checkpoint, envelope.global_seq)
                session.commit()
        except IntegrityError as exc:
            raise StorageError(
                f"state projection failed on {envelope.event_type}"
                f" (global_seq {envelope.global_seq}): {exc.orig}"
            ) from exc
        except SQLAlchemyError as exc:
            raise StorageError(f"state projection failed: {exc}") from exc

    def checkpoint(self) -> int:
        with Session(self._engine) as session:
            return self._checkpoint_row(session).last_global_seq

    def fingerprint(self) -> str:
        """Deterministic content hash of everything this projection currently
        believes — independent of ``checkpoint`` (log *position*, not content).

        ``checkpoint``/lag-based drift detection (status.py) proves a
        projection is caught up with the log; it cannot prove the state it
        computed while catching up was *correct* — a projection with a buggy
        merge rule can sit at ``lag == 0`` and still hold the wrong state
        forever, silently. Two independently-built copies of this projection
        replaying the identical log must fingerprint identically; a mismatch
        at equal checkpoints is exactly that class of bug
        (``maintenance.verify_projection_fidelity`` is the check that uses this).
        """
        with Session(self._engine) as session:
            parts = [
                json.dumps(row.model_dump(mode="json"), sort_keys=True, default=str)
                for row in session.exec(select(MemoryRecord).order_by(col(MemoryRecord.id))).all()
            ]
            parts += [
                json.dumps(row.model_dump(mode="json"), sort_keys=True, default=str)
                for row in session.exec(
                    select(MemoryTagRecord).order_by(
                        col(MemoryTagRecord.memory_id), col(MemoryTagRecord.tag)
                    )
                ).all()
            ]
            parts += [
                json.dumps(row.model_dump(mode="json"), sort_keys=True, default=str)
                for row in session.exec(
                    select(LinkRecord).order_by(
                        col(LinkRecord.source_id),
                        col(LinkRecord.target_id),
                        col(LinkRecord.relation),
                    )
                ).all()
            ]
            parts += [
                json.dumps(row.model_dump(mode="json"), sort_keys=True, default=str)
                for row in session.exec(
                    select(EvidenceRecord).order_by(
                        col(EvidenceRecord.memory_id), col(EvidenceRecord.seq)
                    )
                ).all()
            ]
        return hashlib.sha256("\x1e".join(parts).encode("utf-8")).hexdigest()

    def reset(self) -> None:
        """Truncate all state tables and zero the checkpoint (pre-rebuild)."""
        try:
            with Session(self._engine) as session:
                for table in (EvidenceRecord, MemoryTagRecord, LinkRecord, MemoryRecord):
                    session.exec(delete(table))
                checkpoint = self._checkpoint_row(session)
                checkpoint.last_global_seq = 0
                session.add(checkpoint)
                session.commit()
        except SQLAlchemyError as exc:
            raise StorageError(f"state projection reset failed: {exc}") from exc

    # -- event dispatch ---------------------------------------------------------

    def _apply_event(self, session: Session, envelope: EventEnvelope) -> None:
        payload = envelope.payload
        occurred = to_naive_utc(envelope.occurred_at)
        stream_id = str(envelope.stream_id)
        match payload:
            case ev.MemoryCreated():
                session.add(
                    MemoryRecord(
                        id=str(payload.memory_id),
                        kind=payload.kind,
                        slug=payload.slug,
                        title=payload.title,
                        content=payload.content,
                        attributes=encode_json(dict(payload.attributes)),
                        attributes_schema_version=payload.attributes_schema_version,
                        confidence=payload.confidence,
                        lifetime_policy=payload.lifetime_policy,
                        lifetime_until=(
                            to_naive_utc(payload.lifetime_until) if payload.lifetime_until else None
                        ),
                        visibility=payload.visibility,
                        created_by=envelope.provenance.actor,
                        created_at=occurred,
                        updated_at=occurred,
                        version=envelope.stream_seq,
                    )
                )
                for tag in payload.tags:
                    session.add(MemoryTagRecord(memory_id=str(payload.memory_id), tag=tag))
            case ev.MemoryEdited():
                record = self._memory_row(session, stream_id)
                if payload.title is not None:
                    record.title = payload.title
                if payload.content is not None:
                    record.content = payload.content
                if payload.slug is not None:
                    record.slug = payload.slug
                record.updated_at = occurred
                record.version = envelope.stream_seq
                session.add(record)
            case ev.MemoryTagged():
                for tag in payload.added:
                    session.add(MemoryTagRecord(memory_id=stream_id, tag=tag))
                for tag in payload.removed:
                    row = session.get(MemoryTagRecord, (stream_id, tag))
                    if row is not None:
                        session.delete(row)
                record = self._memory_row(session, stream_id)
                record.updated_at = occurred
                record.version = envelope.stream_seq
                session.add(record)
            case ev.MemoryArchived() | ev.MemoryRestored():
                record = self._memory_row(session, stream_id)
                record.archived = isinstance(payload, ev.MemoryArchived)
                record.updated_at = occurred
                record.version = envelope.stream_seq
                session.add(record)
            case ev.MemoryDeleted():
                session.exec(
                    delete(MemoryTagRecord).where(col(MemoryTagRecord.memory_id) == stream_id)
                )
                session.exec(
                    delete(EvidenceRecord).where(col(EvidenceRecord.memory_id) == stream_id)
                )
                session.exec(delete(LinkRecord).where(col(LinkRecord.source_id) == stream_id))
                existing = session.get(MemoryRecord, stream_id)
                if existing is not None:
                    session.delete(existing)
            case ev.MemoryLinked():
                key = (stream_id, str(payload.target_id), payload.relation)
                if session.get(LinkRecord, key) is None:
                    session.add(
                        LinkRecord(
                            source_id=stream_id,
                            target_id=str(payload.target_id),
                            relation=payload.relation,
                        )
                    )
                record = self._memory_row(session, stream_id)
                record.updated_at = occurred
                record.version = envelope.stream_seq
                session.add(record)
            case ev.MemoryUnlinked():
                edge = session.get(
                    LinkRecord, (stream_id, str(payload.target_id), payload.relation)
                )
                if edge is not None:
                    session.delete(edge)
                record = self._memory_row(session, stream_id)
                record.updated_at = occurred
                record.version = envelope.stream_seq
                session.add(record)
            case ev.MemoryEvidenceAdded():
                # max(seq)+1, not count+1: retraction leaves gaps that must never
                # be reused (ADR-0018).
                head = session.exec(
                    select(func.max(EvidenceRecord.seq)).where(
                        col(EvidenceRecord.memory_id) == stream_id
                    )
                ).one()
                session.add(
                    EvidenceRecord(
                        memory_id=stream_id,
                        seq=(int(head) if head is not None else 0) + 1,
                        evidence_type=payload.evidence_type,
                        value=payload.value,
                        note=payload.note,
                        added_at=occurred,
                        actor=envelope.provenance.actor,
                    )
                )
                record = self._memory_row(session, stream_id)
                record.version = envelope.stream_seq
                session.add(record)
            case ev.MemoryEvidenceRetracted():
                evidence_row = session.get(EvidenceRecord, (stream_id, payload.seq))
                if evidence_row is not None:
                    session.delete(evidence_row)
                record = self._memory_row(session, stream_id)
                record.version = envelope.stream_seq
                session.add(record)
            case ev.MemoryAttributesUpdated():
                record = self._memory_row(session, stream_id)
                merged = dict(json.loads(record.attributes)) | dict(payload.changes)
                record.attributes = encode_json(merged)
                record.attributes_schema_version = payload.attributes_schema_version
                record.updated_at = occurred
                record.version = envelope.stream_seq
                session.add(record)
            case ev.MemoryVisibilityChanged():
                record = self._memory_row(session, stream_id)
                record.visibility = payload.visibility
                record.allowed_actors = encode_json(list(payload.allowed_actors))
                record.updated_at = occurred
                record.version = envelope.stream_seq
                session.add(record)
            case ev.MemoryLifetimeChanged():
                record = self._memory_row(session, stream_id)
                record.lifetime_policy = payload.lifetime_policy
                record.lifetime_until = (
                    to_naive_utc(payload.lifetime_until) if payload.lifetime_until else None
                )
                record.updated_at = occurred
                record.version = envelope.stream_seq
                session.add(record)
            case ev.MemoryConfirmed():
                record = self._memory_row(session, stream_id)
                record.confidence = scoring.confirm_confidence(record.confidence, payload.weight)
                record.last_confirmed_at = occurred
                record.updated_at = occurred
                record.version = envelope.stream_seq
                session.add(record)
            case ev.MemoryContradicted():
                record = self._memory_row(session, stream_id)
                record.confidence = scoring.contradict_confidence(record.confidence, payload.weight)
                record.updated_at = occurred
                record.version = envelope.stream_seq
                session.add(record)
            case ev.MemoryConfidenceRestored():
                record = self._memory_row(session, stream_id)
                record.confidence = payload.confidence
                record.last_confirmed_at = (
                    to_naive_utc(payload.last_confirmed_at)
                    if payload.last_confirmed_at is not None
                    else None
                )
                record.updated_at = occurred
                record.version = envelope.stream_seq
                session.add(record)
            case ev.MemoryImportanceAdjusted():
                record = self._memory_row(session, stream_id)
                if payload.pinned is not None:
                    record.pinned = payload.pinned
                if payload.clear_user_weight:
                    record.user_weight = None
                elif payload.user_weight is not None:
                    record.user_weight = payload.user_weight
                record.updated_at = occurred
                record.version = envelope.stream_seq
                session.add(record)
            case ev.MemoryAccessed():
                record = self._memory_row(session, stream_id)
                record.access_count += 1
                record.last_accessed_at = occurred
                record.version = envelope.stream_seq
                session.add(record)
            case _:
                # Future-phase events advance the checkpoint without touching state;
                # their projections land with their phases.
                return

    def _memory_row(self, session: Session, memory_id: str) -> MemoryRecord:
        record = session.get(MemoryRecord, memory_id)
        if record is None:
            raise StorageError(f"state projection out of order: no row for {memory_id}")
        return record

    def _advance_checkpoint(
        self, session: Session, checkpoint: ProjectionCheckpointRecord, new_seq: int
    ) -> None:
        """Move the checkpoint from the value ``checkpoint`` was read at up to
        ``new_seq`` -- a compare-and-swap, not a blind overwrite.

        The previous ``checkpoint.last_global_seq = new_seq; session.add(...)``
        wrote unconditionally, keyed only by the row's primary key: whichever
        of two overlapping writers (a rebuild pass and a live write, the same
        scenario ``rebuild_projections`` already defends against) committed
        *last* simply won, silently regressing the checkpoint back down if it
        happened to be the one further behind. That erased the record that a
        *later* envelope had already been durably applied, so a rebuild
        reaching that envelope on its own next iteration re-applied it —
        for a non-conflicting event (no UNIQUE constraint at stake, e.g.
        ``MemoryAccessed``), that duplicate application landed with no error
        at all: ``engram rebuild`` reported success and the checkpoint ended
        up matching the log head (``engram status``: healthy) over a
        projection that had just silently double-counted an event. Confirmed
        via real-thread reproduction (PRE-M10 follow-up finding, concurrency
        P0 — a second, narrower instance of the same class the original P0
        fix closed one layer up).

        A single ``UPDATE ... WHERE last_global_seq = <the value we read>``
        makes the write conditional on nothing having changed the row since:
        zero rows affected means some other writer already moved it, so this
        transaction's own view of "what's already applied" went stale
        mid-flight and it must not blindly claim otherwise.
        """
        state = inspect(checkpoint)
        assert state is not None
        if state.transient:
            # No row exists yet for this projection (bootstrap only --
            # migration 0006 seeds it in the ordinary case): a plain INSERT,
            # nothing to compare-and-swap against.
            checkpoint.last_global_seq = new_seq
            session.add(checkpoint)
            return
        prior = checkpoint.last_global_seq
        result = session.exec(
            update(ProjectionCheckpointRecord)
            .where(col(ProjectionCheckpointRecord.projection_name) == _NAME)
            .where(col(ProjectionCheckpointRecord.last_global_seq) == prior)
            .values(last_global_seq=new_seq)
        )
        if result.rowcount != 1:
            raise StorageError(
                f"{_NAME} projection checkpoint moved from {prior} to something"
                f" else while applying global_seq {new_seq} — a concurrent"
                " writer changed it first"
            )

    def _checkpoint_row(self, session: Session) -> ProjectionCheckpointRecord:
        checkpoint = session.exec(
            select(ProjectionCheckpointRecord).where(
                ProjectionCheckpointRecord.projection_name == _NAME
            )
        ).first()
        if checkpoint is None:
            checkpoint = ProjectionCheckpointRecord(projection_name=_NAME, last_global_seq=0)
        return checkpoint
