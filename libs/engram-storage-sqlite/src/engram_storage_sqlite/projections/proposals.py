"""The proposals projection: folds proposal events into the review-queue table.

Same contract as every projection — checkpointed, idempotent per ``global_seq``,
row change and checkpoint advance in one transaction, fully rebuilt by replay.
"""

from sqlalchemy import inspect, update
from sqlalchemy.engine import Engine
from sqlalchemy.exc import SQLAlchemyError
from sqlmodel import Session, col, delete, select

from engram_core.domain import events as ev
from engram_core.domain.errors import StorageError
from engram_events import EventEnvelope
from engram_storage_sqlite.codec import to_naive_utc
from engram_storage_sqlite.models import ProjectionCheckpointRecord, ProposalRecord

_NAME = "proposals"


class ProposalProjection:
    """proposals / projection_checkpoints."""

    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    @property
    def name(self) -> str:
        return _NAME

    def handles(self, event_type: str) -> bool:
        # Observe everything so the checkpoint tracks the whole log (see state.py).
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
        except SQLAlchemyError as exc:
            raise StorageError(f"proposals projection failed: {exc}") from exc

    def checkpoint(self) -> int:
        with Session(self._engine) as session:
            return self._checkpoint_row(session).last_global_seq

    def reset(self) -> None:
        try:
            with Session(self._engine) as session:
                session.exec(delete(ProposalRecord))
                checkpoint = self._checkpoint_row(session)
                checkpoint.last_global_seq = 0
                session.add(checkpoint)
                session.commit()
        except SQLAlchemyError as exc:
            raise StorageError(f"proposals projection reset failed: {exc}") from exc

    # -- event dispatch ---------------------------------------------------------

    def _apply_event(self, session: Session, envelope: EventEnvelope) -> None:
        payload = envelope.payload
        occurred = to_naive_utc(envelope.occurred_at)
        stream_id = str(envelope.stream_id)
        match payload:
            case ev.ProposalOpened():
                session.add(
                    ProposalRecord(
                        id=str(payload.proposal_id),
                        title=payload.title,
                        description=payload.description,
                        status="pending",
                        draft_count=len(payload.proposed_events),
                        opened_by=envelope.provenance.actor,
                        created_at=occurred,
                        updated_at=occurred,
                        version=envelope.stream_seq,
                    )
                )
            case ev.ProposalApproved() | ev.ProposalRejected():
                record = self._proposal_row(session, stream_id)
                record.status = (
                    "approved" if isinstance(payload, ev.ProposalApproved) else "rejected"
                )
                record.review_note = payload.note
                record.updated_at = occurred
                record.version = envelope.stream_seq
                session.add(record)
            case ev.ProposalMerged():
                record = self._proposal_row(session, stream_id)
                record.status = "merged"
                record.updated_at = occurred
                record.version = envelope.stream_seq
                session.add(record)
            case ev.ProposalUndone():
                record = self._proposal_row(session, stream_id)
                record.status = "undone"
                record.updated_at = occurred
                record.version = envelope.stream_seq
                session.add(record)
            case _:
                return  # future proposal events advance the checkpoint only

    def _proposal_row(self, session: Session, proposal_id: str) -> ProposalRecord:
        record = session.get(ProposalRecord, proposal_id)
        if record is None:
            raise StorageError(f"proposals projection out of order: no row for {proposal_id}")
        return record

    def _advance_checkpoint(
        self, session: Session, checkpoint: ProjectionCheckpointRecord, new_seq: int
    ) -> None:
        """Move the checkpoint from the value ``checkpoint`` was read at up to
        ``new_seq`` -- a compare-and-swap, not a blind overwrite.

        Same contract and same reasoning as ``StateProjection._advance_checkpoint``:
        an unconditional ``checkpoint.last_global_seq = new_seq; session.add(...)``
        write, keyed only by the row's primary key, lets an overlapping rebuild
        pass and live write silently regress the checkpoint back down — erasing
        the record that a later envelope was already durably applied, so a
        rebuild reaching it later re-applies it. For a non-conflicting mutation
        here (a status UPDATE with no UNIQUE constraint at stake, e.g.
        ``ProposalApproved``/``ProposalRejected``/``ProposalMerged``/
        ``ProposalUndone``), that duplicate application lands with no error at
        all: rebuild reports success and the checkpoint matches the log head
        over a proposal record that was just silently double-applied.
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
