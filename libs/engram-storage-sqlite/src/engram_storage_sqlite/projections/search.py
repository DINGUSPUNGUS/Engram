"""The search projection: folds memory events into the ``memory_fts`` FTS5 table.

Same contract as the state projection — checkpointed, idempotent per ``global_seq``,
row change and checkpoint advance in one transaction — and deliberately
self-contained: it maintains title/content/tags from the events alone, never by
reading another projection's tables, so projections stay independently rebuildable.
"""

from sqlalchemy import inspect, text, update
from sqlalchemy.engine import Engine
from sqlalchemy.exc import SQLAlchemyError
from sqlmodel import Session, col, select

from engram_core.domain import events as ev
from engram_core.domain.errors import StorageError
from engram_events import EventEnvelope
from engram_storage_sqlite.models import ProjectionCheckpointRecord

_NAME = "search"


class SearchProjection:
    """memory_fts (FTS5) + its projection_checkpoints row."""

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
            raise StorageError(f"search projection failed: {exc}") from exc

    def checkpoint(self) -> int:
        with Session(self._engine) as session:
            return self._checkpoint_row(session).last_global_seq

    def reset(self) -> None:
        """Empty the FTS table and zero the checkpoint (pre-rebuild)."""
        try:
            with Session(self._engine) as session:
                session.connection().execute(text("DELETE FROM memory_fts"))
                checkpoint = self._checkpoint_row(session)
                checkpoint.last_global_seq = 0
                session.add(checkpoint)
                session.commit()
        except SQLAlchemyError as exc:
            raise StorageError(f"search projection reset failed: {exc}") from exc

    # -- event dispatch ---------------------------------------------------------

    def _apply_event(self, session: Session, envelope: EventEnvelope) -> None:
        payload = envelope.payload
        stream_id = str(envelope.stream_id)
        connection = session.connection()
        match payload:
            case ev.MemoryCreated():
                connection.execute(
                    text(
                        "INSERT INTO memory_fts (memory_id, title, content, tags)"
                        " VALUES (:id, :title, :content, :tags)"
                    ),
                    {
                        "id": str(payload.memory_id),
                        "title": payload.title,
                        "content": payload.content,
                        "tags": " ".join(payload.tags),
                    },
                )
            case ev.MemoryEdited():
                assignments = {}
                if payload.title is not None:
                    assignments["title"] = payload.title
                if payload.content is not None:
                    assignments["content"] = payload.content
                if assignments:
                    clause = ", ".join(f"{column} = :{column}" for column in assignments)
                    connection.execute(
                        text(f"UPDATE memory_fts SET {clause} WHERE memory_id = :id"),
                        {**assignments, "id": stream_id},
                    )
            case ev.MemoryTagged():
                row = connection.execute(
                    text("SELECT tags FROM memory_fts WHERE memory_id = :id"),
                    {"id": stream_id},
                ).first()
                if row is None:
                    raise StorageError(f"search projection out of order: no row for {stream_id}")
                tags = [tag for tag in str(row[0]).split() if tag not in payload.removed]
                tags.extend(tag for tag in payload.added if tag not in tags)
                connection.execute(
                    text("UPDATE memory_fts SET tags = :tags WHERE memory_id = :id"),
                    {"tags": " ".join(tags), "id": stream_id},
                )
            case ev.MemoryDeleted():
                connection.execute(
                    text("DELETE FROM memory_fts WHERE memory_id = :id"), {"id": stream_id}
                )
            case _:
                # Archived stays searchable (the executor filters); other events
                # carry no indexed text — advance the checkpoint only.
                return

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
        here (an UPDATE with no UNIQUE constraint at stake, e.g. ``MemoryEdited``
        or ``MemoryTagged``), that duplicate application lands with no error at
        all: rebuild reports success and the checkpoint matches the log head
        over search state that was just silently double-applied.
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
