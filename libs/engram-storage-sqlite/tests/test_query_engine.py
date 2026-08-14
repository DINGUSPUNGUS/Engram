"""The query engine (ADR-0016) against real projections, plus THE M2 invariant:
dropping any projection table is fully recoverable by replay."""

from collections.abc import Sequence
from datetime import UTC, datetime

import pytest
from sqlalchemy import text
from sqlalchemy.engine import Engine
from sqlmodel import Session

from engram_core.application.commands.memory_commands import MemoryCommandService
from engram_core.application.dto import CreateMemoryInput, EditMemoryInput, Page, QueryHit
from engram_core.application.queries.query_language import parse_query
from engram_core.domain.events import build_registry
from engram_core.domain.kinds import build_kind_registry
from engram_core.domain.values import MemoryId, MemoryKind
from engram_events import EventEnvelope, InProcessEventBus, Provenance, SystemClock
from engram_storage_sqlite.event_store import SqliteEventStore
from engram_storage_sqlite.maintenance import rebuild_projections
from engram_storage_sqlite.models import LinkRecord
from engram_storage_sqlite.projections.search import SearchProjection
from engram_storage_sqlite.projections.state import StateProjection
from engram_storage_sqlite.query_engine import SqliteQueryEngine
from engram_storage_sqlite.repositories import SqliteMemoryRepository

USER = Provenance(actor="user", detail="test")
ASSISTANT = Provenance(actor="claude", session_id="s42")
KINDS = build_kind_registry()


class _Harness:
    """The CLI runtime's shape: both projections fed by the bus."""

    def __init__(self, engine: Engine) -> None:
        self.store = SqliteEventStore(engine, build_registry())
        self.state = StateProjection(engine)
        self.search = SearchProjection(engine)
        bus = InProcessEventBus()
        projections = (self.state, self.search)

        def _project(envelope: EventEnvelope) -> None:
            for projection in projections:
                if projection.handles(envelope.event_type):
                    projection.apply(envelope)

        bus.subscribe(_project)
        self.repository = SqliteMemoryRepository(self.store, KINDS)
        self.commands = MemoryCommandService(self.repository, bus, SystemClock(), KINDS, self.store)
        self.engine_port = SqliteQueryEngine(engine)

    def query(
        self, query_string: str, *, limit: int = 20, cursor: str | None = None
    ) -> Page[QueryHit]:
        spec = parse_query(query_string, now=datetime.now(UTC), kinds=KINDS)
        return self.engine_port.query(spec, cursor=cursor, limit=limit)


def _ids(hits: Sequence[QueryHit]) -> set[MemoryId]:
    return {hit.memory.id for hit in hits}


@pytest.fixture
def harness(engine: Engine) -> _Harness:
    return _Harness(engine)


@pytest.fixture
def seeded(harness: _Harness, engine: Engine) -> dict[str, MemoryId]:
    project_id = harness.commands.create_memory(
        CreateMemoryInput(
            kind=MemoryKind.PROJECT,
            title="engram",
            content="the memory engine",
            attributes={"name": "engram", "status": "active"},
            tags=("oss",),
        ),
        USER,
    )
    fact_id = harness.commands.create_memory(
        CreateMemoryInput(
            kind=MemoryKind.FACT,
            title="User prefers dark mode",
            content="always dark themes",
            attributes={"statement": "User prefers dark mode"},
            tags=("ui",),
        ),
        ASSISTANT,
    )
    archived_id = harness.commands.create_memory(
        CreateMemoryInput(
            kind=MemoryKind.FACT,
            title="Old fact about coffee",
            content="",
            attributes={"statement": "drinks coffee"},
        ),
        USER,
    )
    harness.commands.archive_memory(archived_id, "example", USER)
    # Links land as commands in M4; the query engine reads the projection table,
    # so adjacency is seeded directly.
    with Session(engine) as session:
        session.add(LinkRecord(source_id=str(fact_id), target_id=str(project_id), relation="about"))
        session.commit()
    return {"project": project_id, "fact": fact_id, "archived": archived_id}


@pytest.mark.integration
class TestOperators:
    def test_free_text_matches_with_snippet_and_score(
        self, harness: _Harness, seeded: dict[str, MemoryId]
    ) -> None:
        page = harness.query("dark")
        assert _ids(page.items) == {seeded["fact"]}
        hit = page.items[0]
        assert hit.snippet and "dark" in hit.snippet.lower()
        assert hit.score is not None

    def test_kind_and_attribute_fallthrough(
        self, harness: _Harness, seeded: dict[str, MemoryId]
    ) -> None:
        assert _ids(harness.query("kind:project").items) == {seeded["project"]}
        assert _ids(harness.query("status:active").items) == {seeded["project"]}
        assert harness.query("status:paused").items == ()

    def test_tag(self, harness: _Harness, seeded: dict[str, MemoryId]) -> None:
        assert _ids(harness.query("tag:oss").items) == {seeded["project"]}

    def test_effective_confidence_comparison(
        self, harness: _Harness, seeded: dict[str, MemoryId]
    ) -> None:
        # User prior 0.95 vs assistant prior 0.60; nothing has decayed yet.
        assert _ids(harness.query("confidence>0.9").items) == {seeded["project"]}
        assert seeded["fact"] in _ids(harness.query("confidence<0.7").items)

    def test_archived_excluded_by_default_and_selectable(
        self, harness: _Harness, seeded: dict[str, MemoryId]
    ) -> None:
        assert seeded["archived"] not in _ids(harness.query("kind:fact").items)
        assert _ids(harness.query("kind:fact is:archived").items) == {seeded["archived"]}

    def test_linked_by_slug_either_direction(
        self, harness: _Harness, seeded: dict[str, MemoryId]
    ) -> None:
        project_slug = harness.engine_port.get(seeded["project"]).slug
        fact_slug = harness.engine_port.get(seeded["fact"]).slug
        assert _ids(harness.query(f"linked:{project_slug}").items) == {seeded["fact"]}
        assert _ids(harness.query(f"linked:{fact_slug}").items) == {seeded["project"]}
        assert harness.query("linked:no-such-slug").items == ()

    def test_has_links(self, harness: _Harness, seeded: dict[str, MemoryId]) -> None:
        assert _ids(harness.query("has:links").items) == {seeded["project"], seeded["fact"]}

    def test_updated_recency(self, harness: _Harness, seeded: dict[str, MemoryId]) -> None:
        everything = _ids(harness.query("updated:last30days kind:fact").items)
        assert seeded["fact"] in everything

    def test_combined_text_and_filters(
        self, harness: _Harness, seeded: dict[str, MemoryId]
    ) -> None:
        assert _ids(harness.query("engram kind:project status:active").items) == {seeded["project"]}
        assert harness.query("engram kind:fact").items == ()

    def test_cursor_pagination(self, harness: _Harness, seeded: dict[str, MemoryId]) -> None:
        first = harness.query("updated:last30days", limit=1)
        assert len(first.items) == 1 and first.next_cursor == "1"
        second = harness.query("updated:last30days", limit=1, cursor=first.next_cursor)
        assert len(second.items) == 1
        assert _ids(first.items) != _ids(second.items)


@pytest.mark.integration
class TestProjectionMaintenance:
    def test_edit_and_retag_update_the_index(
        self, harness: _Harness, seeded: dict[str, MemoryId]
    ) -> None:
        version = harness.engine_port.get(seeded["fact"]).version
        harness.commands.edit_memory(
            seeded["fact"],
            EditMemoryInput(expected_version=version, title="User prefers light mode"),
            USER,
        )
        assert _ids(harness.query("light").items) == {seeded["fact"]}
        assert harness.query("dark").items != ()  # content still says dark themes
        harness.commands.tag_memory(
            seeded["fact"], add=("appearance",), remove=("ui",), provenance=USER
        )
        assert _ids(harness.query("appearance").items) == {seeded["fact"]}
        assert harness.query("tag:ui").items == ()

    def test_delete_removes_from_index(
        self, harness: _Harness, seeded: dict[str, MemoryId]
    ) -> None:
        harness.commands.delete_memory(seeded["fact"], "test", USER)
        assert harness.query("dark").items == ()

    def test_dropping_the_fts_table_contents_is_fully_recoverable(
        self, harness: _Harness, seeded: dict[str, MemoryId], engine: Engine
    ) -> None:
        """THE M2 invariant: any projection is disposable; replay restores it."""
        before = [(str(h.memory.id), h.snippet) for h in harness.query("dark").items]
        assert before
        with Session(engine) as session:
            session.connection().execute(text("DELETE FROM memory_fts"))
            session.commit()
        assert harness.query("dark").items == ()  # the index is really gone

        rebuild_projections(harness.store, [harness.state, harness.search])

        after = [(str(h.memory.id), h.snippet) for h in harness.query("dark").items]
        assert after == before


@pytest.mark.integration
class TestQueryHydrationIsDeferredToThePage:
    """M9 performance pass regression: ``query()`` previously hydrated a full
    ``MemoryReadModel`` — several extra queries each (tags/links/evidence,
    ``_read_model``) — for *every* SQL-matched candidate, before slicing to
    ``limit``. Measured cost at 1000 memories: ~6.4s mean per free-text search
    (evaluations/results/performance_baseline.json — machine-local, not
    committed). Proven here without depending on wall-clock timing: hydration
    must be called exactly ``limit`` times, never once per matched row.
    """

    def test_hydration_count_matches_the_page_not_the_match_count(
        self, harness: _Harness, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        for i in range(40):
            harness.commands.create_memory(
                CreateMemoryInput(
                    kind=MemoryKind.FACT,
                    title=f"searchable memory {i}",
                    content="shared searchable content",
                    attributes={"statement": f"s{i}"},
                ),
                USER,
            )

        calls = {"count": 0}
        original = harness.engine_port._read_model

        def _counting_read_model(session: Session, record: object) -> object:
            calls["count"] += 1
            return original(session, record)  # type: ignore[arg-type]

        monkeypatch.setattr(harness.engine_port, "_read_model", _counting_read_model)

        page = harness.query("searchable", limit=5)

        assert len(page.items) == 5
        assert page.next_cursor is not None  # 40 matches, 5 returned — more exist
        assert calls["count"] == 5, (
            f"hydrated {calls['count']} candidates for a limit=5 page out of 40"
            " matches — full hydration must be deferred until after pagination"
        )

    def test_confidence_and_stale_filters_still_narrow_results_correctly(
        self, harness: _Harness, seeded: dict[str, MemoryId]
    ) -> None:
        """The cheap-candidate filtering path must agree exactly with what
        full hydration would have computed — same effective_confidence, same
        staleness_threshold comparison, just without the extra queries."""
        below = harness.query("confidence<0.99").items
        above = harness.query("confidence>0.01").items
        assert _ids(below) | _ids(above) >= {seeded["fact"], seeded["project"]}
        # Freshly created: not stale, so `is:stale` must exclude it.
        assert seeded["fact"] not in _ids(harness.query("is:stale").items)
