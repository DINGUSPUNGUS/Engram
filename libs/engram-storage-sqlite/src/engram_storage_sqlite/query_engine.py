"""The SQLite query executor: translates a ``MemoryQuerySpec`` into projections SQL.

Implements the ``QueryEngine`` port (ADR-0016). SQL-able terms (kind, tags, slug,
attributes, dates, has:, linked:, visibility, archived, pinned, text) filter in the
database; derived-value terms (``confidence>``, ``is:stale``) are computed per
candidate — derived scores are functions of *now* and are never stored (ADR-0009).
Exact and cheap at personal-memory scale; the sanctioned fix if that ever changes is
a scoring projection, not stored scores.

Ranked results use an opaque offset cursor (bm25 order is not id order).
"""

from collections.abc import Sequence
from datetime import UTC, datetime
from uuid import UUID

import sqlalchemy as sa
from sqlmodel import Session, col, select
from sqlmodel.sql.expression import SelectOfScalar

from engram_core.application.dto import ConfidenceFilter, MemoryQuerySpec, Page, QueryHit
from engram_core.domain.errors import ValidationError
from engram_core.domain.scoring import ScoringConfig, effective_confidence
from engram_core.domain.values import MemoryKind
from engram_storage_sqlite.codec import from_naive_utc, to_naive_utc
from engram_storage_sqlite.models import (
    EvidenceRecord,
    LinkRecord,
    MemoryRecord,
    MemoryTagRecord,
)
from engram_storage_sqlite.queries import SqliteMemoryQuery

_SNIPPET_SQL = (
    "SELECT memory_id, snippet(memory_fts, -1, '[', ']', '…', 12) AS snip,"
    " bm25(memory_fts) AS rank FROM memory_fts WHERE memory_fts MATCH :q"
)


def _matches_confidence(value: float, condition: ConfidenceFilter) -> bool:
    match condition.op:
        case ">":
            return value > condition.value
        case ">=":
            return value >= condition.value
        case "<":
            return value < condition.value
        case "<=":
            return value <= condition.value
    raise ValidationError(f"unknown confidence comparison: {condition.op!r}")


def _parse_cursor(cursor: str | None) -> int:
    if cursor is None:
        return 0
    try:
        offset = int(cursor)
    except ValueError:
        raise ValidationError(f"bad cursor: {cursor!r}") from None
    if offset < 0:
        raise ValidationError(f"bad cursor: {cursor!r}")
    return offset


class SqliteQueryEngine(SqliteMemoryQuery):
    """The read-side adapter's query half: one class serves both the ``MemoryQuery``
    and ``QueryEngine`` ports (same engine, same derived-score computation)."""

    def __init__(self, engine: sa.engine.Engine, config: ScoringConfig | None = None) -> None:
        super().__init__(engine, config)

    @property
    def supports_vectors(self) -> bool:
        return False  # sqlite-vec arrives in M5 behind this same flag

    def query(
        self,
        spec: MemoryQuerySpec,
        *,
        cursor: str | None = None,
        limit: int = 20,
    ) -> Page[QueryHit]:
        offset = _parse_cursor(cursor)
        with self._session() as session:
            text_hits = self._text_hits(session, spec.text) if spec.text else None
            if text_hits is not None and not text_hits:
                return Page(items=(), next_cursor=None)
            linked_id = self._resolve_linked(session, spec.linked) if spec.linked else None
            if spec.linked and linked_id is None:
                return Page(items=(), next_cursor=None)

            statement = self._build_statement(spec, text_hits, linked_id)
            records = session.exec(statement).all()
            candidates = self._filter_and_rank(records, spec, text_hits)
            page_candidates = candidates[offset : offset + limit]
            # Full hydration (tags/evidence/links + retention scoring — several
            # extra queries each, by design in _read_model) only for the page
            # actually returned, not every SQL-matched candidate: fetching it
            # for every match before slicing to `limit` measured at ~6s for a
            # free-text search over a 1000-memory space (M9 performance pass) —
            # almost all of that work was discarded immediately after.
            hits = [
                QueryHit(memory=self._read_model(session, record), snippet=snippet, score=score)
                for record, snippet, score in page_candidates
            ]

        next_cursor = str(offset + limit) if len(candidates) > offset + limit else None
        return Page(items=tuple(hits), next_cursor=next_cursor)

    # -- pieces -------------------------------------------------------------------

    def _text_hits(self, session: Session, query: str) -> dict[str, tuple[str, float]]:
        rows = session.connection().execute(sa.text(_SNIPPET_SQL), {"q": query}).all()
        return {str(row[0]): (str(row[1]), float(row[2])) for row in rows}

    def _resolve_linked(self, session: Session, target: str) -> str | None:
        """``linked:`` takes a UUID or a slug; unknown targets match nothing."""
        try:
            return str(UUID(target))
        except ValueError:
            row = session.exec(select(MemoryRecord.id).where(MemoryRecord.slug == target)).first()
            return row

    def _build_statement(
        self,
        spec: MemoryQuerySpec,
        text_hits: dict[str, tuple[str, float]] | None,
        linked_id: str | None,
    ) -> SelectOfScalar[MemoryRecord]:
        statement = select(MemoryRecord).order_by(col(MemoryRecord.id))
        if text_hits is not None:
            statement = statement.where(col(MemoryRecord.id).in_(text_hits))
        if spec.kind is not None:
            statement = statement.where(MemoryRecord.kind == spec.kind.value)
        if spec.slug is not None:
            statement = statement.where(MemoryRecord.slug == spec.slug)
        if spec.visibility is not None:
            statement = statement.where(MemoryRecord.visibility == spec.visibility.value)
        only_archived = spec.archived is True
        statement = statement.where(col(MemoryRecord.archived) == only_archived)
        if spec.pinned is not None:
            statement = statement.where(col(MemoryRecord.pinned) == spec.pinned)
        if spec.updated_after is not None:
            statement = statement.where(
                col(MemoryRecord.updated_at) >= to_naive_utc(spec.updated_after)
            )
        if spec.created_after is not None:
            statement = statement.where(
                col(MemoryRecord.created_at) >= to_naive_utc(spec.created_after)
            )
        for tag in spec.tags:
            statement = statement.where(
                sa.exists(
                    select(MemoryTagRecord.memory_id).where(
                        col(MemoryTagRecord.memory_id) == col(MemoryRecord.id),
                        MemoryTagRecord.tag == tag,
                    )
                )
            )
        for key, value in spec.attributes:
            statement = statement.where(
                sa.func.json_extract(MemoryRecord.attributes, f"$.{key}") == value
            )
        if "evidence" in spec.has:
            statement = statement.where(
                sa.exists(
                    select(EvidenceRecord.memory_id).where(
                        col(EvidenceRecord.memory_id) == col(MemoryRecord.id)
                    )
                )
            )
        if "links" in spec.has:
            statement = statement.where(self._any_link_exists())
        if linked_id is not None:
            statement = statement.where(self._linked_to_exists(linked_id))
        return statement

    def _any_link_exists(self) -> sa.ColumnElement[bool]:
        return sa.exists(
            select(LinkRecord.source_id).where(
                sa.or_(
                    col(LinkRecord.source_id) == col(MemoryRecord.id),
                    col(LinkRecord.target_id) == col(MemoryRecord.id),
                )
            )
        )

    def _linked_to_exists(self, linked_id: str) -> sa.ColumnElement[bool]:
        """Adjacency in either direction — edges store the canonical direction only."""
        return sa.exists(
            select(LinkRecord.source_id).where(
                sa.or_(
                    sa.and_(
                        col(LinkRecord.source_id) == col(MemoryRecord.id),
                        col(LinkRecord.target_id) == linked_id,
                    ),
                    sa.and_(
                        col(LinkRecord.source_id) == linked_id,
                        col(LinkRecord.target_id) == col(MemoryRecord.id),
                    ),
                )
            )
        )

    def _filter_and_rank(
        self,
        records: Sequence[MemoryRecord],
        spec: MemoryQuerySpec,
        text_hits: dict[str, tuple[str, float]] | None,
    ) -> list[tuple[MemoryRecord, str | None, float | None]]:
        """Confidence/staleness filtering and text-relevance ranking — computed
        straight from each record's own columns, with zero extra queries per
        candidate. Deliberately returns raw records, not hydrated
        ``MemoryReadModel``s: full hydration (``_read_model``) is for the
        caller to apply *after* this list is paginated, not before.

        ``effective_confidence`` needs only ``confidence``/``kind``/
        ``last_confirmed_at``/``created_at`` off the record itself — none of
        tags, links, or evidence, which is what made deferring hydration safe.
        """
        now = datetime.now(UTC)
        candidates: list[tuple[MemoryRecord, str | None, float | None]] = []
        for record in records:
            if spec.confidence is not None or spec.stale is not None:
                kind = MemoryKind(record.kind)
                anchor = from_naive_utc(record.last_confirmed_at or record.created_at)
                c_eff = effective_confidence(record.confidence, kind, anchor, now, self._config)
                if spec.confidence is not None and not _matches_confidence(c_eff, spec.confidence):
                    continue
                if spec.stale is not None:
                    stale = c_eff < self._config.staleness_threshold[kind]
                    if stale is not spec.stale:
                        continue
            snippet, score = (None, None)
            if text_hits is not None:
                snip, rank = text_hits[str(record.id)]
                # bm25 is lower-is-better; negate so callers can sort descending.
                snippet, score = snip, -rank
            candidates.append((record, snippet, score))
        if text_hits is not None:
            candidates.sort(key=lambda c: (-(c[2] or 0.0), str(c[0].id)))
        return candidates
