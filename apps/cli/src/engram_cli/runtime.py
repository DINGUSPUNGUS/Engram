"""The CLI's composition root: the only place that names adapter implementations."""

from dataclasses import dataclass

from sqlalchemy.engine import Engine

from engram_cli import __version__
from engram_cli.config import CliSettings
from engram_core.application.commands.memory_commands import MemoryCommandService
from engram_core.application.commands.proposal_commands import ProposalCommandService
from engram_core.application.queries.history_queries import HistoryQueryService
from engram_core.application.queries.memory_queries import MemoryQueryService
from engram_core.application.queries.search_queries import SearchQueryService
from engram_core.application.queries.timeline_queries import TimelineQueryService
from engram_core.domain.errors import NotFoundError
from engram_core.domain.events import build_registry
from engram_core.domain.kinds import build_kind_registry
from engram_events import EventEnvelope, InProcessEventBus, SystemClock
from engram_export_git.exporter import ExportEngine
from engram_export_git.importer import ImportEngine
from engram_storage_sqlite.event_store import SqliteEventStore, create_sqlite_engine
from engram_storage_sqlite.maintenance import rebuild_projections
from engram_storage_sqlite.projections.search import SearchProjection
from engram_storage_sqlite.projections.state import StateProjection
from engram_storage_sqlite.query_engine import SqliteQueryEngine
from engram_storage_sqlite.repositories import (
    SqliteMemoryRepository,
    SqliteProposalRepository,
)
from engram_storage_sqlite.status import SpaceStatus, space_status


@dataclass
class Runtime:
    engine: Engine
    store: SqliteEventStore
    state_projection: StateProjection
    search_projection: SearchProjection
    commands: MemoryCommandService
    proposals: ProposalCommandService
    queries: MemoryQueryService
    search: SearchQueryService
    timeline: TimelineQueryService
    history: HistoryQueryService
    exporter: ExportEngine
    importer: ImportEngine

    def rebuild(self) -> int:
        return rebuild_projections(self.store, self._projections())

    def status(self) -> SpaceStatus:
        return space_status(self.engine, self._projections())

    def _projections(self) -> tuple[StateProjection | SearchProjection, ...]:
        return (self.state_projection, self.search_projection)


def build_runtime(settings: CliSettings) -> Runtime:
    db_path = settings.resolved_db_path
    if not db_path.exists():
        raise NotFoundError(f"no engram database at {db_path} — run `engram init` first")
    engine = create_sqlite_engine(f"sqlite:///{db_path}")
    registry = build_registry()
    kinds = build_kind_registry()
    store = SqliteEventStore(engine, registry)
    state = StateProjection(engine)
    search = SearchProjection(engine)

    bus = InProcessEventBus()
    projections = (state, search)

    def _project(envelope: EventEnvelope) -> None:
        for projection in projections:
            if projection.handles(envelope.event_type):
                projection.apply(envelope)

    bus.subscribe(_project)

    repository = SqliteMemoryRepository(store, kinds)
    proposal_repository = SqliteProposalRepository(store)
    query = SqliteQueryEngine(engine)
    clock = SystemClock()
    proposals = ProposalCommandService(proposal_repository, repository, bus, clock)
    return Runtime(
        engine=engine,
        store=store,
        state_projection=state,
        search_projection=search,
        commands=MemoryCommandService(repository, bus, clock, kinds),
        proposals=proposals,
        queries=MemoryQueryService(query),
        search=SearchQueryService(query, clock, kinds),
        timeline=TimelineQueryService(query),
        history=HistoryQueryService(repository),
        exporter=ExportEngine(query, store, engine_version=__version__),
        importer=ImportEngine(store, registry, kinds, proposals),
    )
