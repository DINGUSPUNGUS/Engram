"""The CLI's composition root: the only place that names adapter implementations."""

from dataclasses import dataclass

from sqlalchemy.engine import Engine

from engram_cli import __version__
from engram_cli.config import CliSettings
from engram_core.application.commands.memory_commands import MemoryCommandService
from engram_core.application.commands.proposal_commands import ProposalCommandService
from engram_core.application.queries.history_queries import HistoryQueryService
from engram_core.application.queries.memory_queries import MemoryQueryService
from engram_core.application.queries.proposal_queries import ProposalQueryService
from engram_core.application.queries.search_queries import SearchQueryService
from engram_core.application.queries.timeline_queries import TimelineQueryService
from engram_core.domain.errors import NotFoundError
from engram_core.domain.events import build_registry
from engram_core.domain.kinds import build_kind_registry
from engram_events import EventEnvelope, InProcessEventBus, SystemClock
from engram_export_git.exporter import ExportEngine
from engram_export_git.importer import ImportEngine
from engram_storage_sqlite.event_store import SqliteEventStore, create_sqlite_engine
from engram_storage_sqlite.maintenance import (
    ProjectionFidelityReport,
    rebuild_projections,
    verify_projection_fidelity,
)
from engram_storage_sqlite.migrate import require_current_schema
from engram_storage_sqlite.projections.proposals import ProposalProjection
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
    query_engine: SqliteQueryEngine
    state_projection: StateProjection
    search_projection: SearchProjection
    proposals_projection: ProposalProjection
    commands: MemoryCommandService
    proposals: ProposalCommandService
    queries: MemoryQueryService
    proposal_queries: ProposalQueryService
    search: SearchQueryService
    timeline: TimelineQueryService
    history: HistoryQueryService
    exporter: ExportEngine
    importer: ImportEngine

    def rebuild(self) -> int:
        return rebuild_projections(self.store, self._projections())

    def status(self) -> SpaceStatus:
        return space_status(self.engine, self._projections())

    def verify_fidelity(self) -> ProjectionFidelityReport:
        """Differential rebuild check: catches a state projection that is
        caught up (checkpoint lag 0) but computed the wrong content — a full
        log replay, so opt-in (``engram status --verify``), not automatic."""
        return verify_projection_fidelity(self.store, self.state_projection)

    def _projections(
        self,
    ) -> tuple[StateProjection | SearchProjection | ProposalProjection, ...]:
        return (self.state_projection, self.search_projection, self.proposals_projection)


def build_runtime(settings: CliSettings) -> Runtime:
    db_path = settings.resolved_db_path
    if not db_path.exists():
        raise NotFoundError(f"no engram database at {db_path} — run `engram init` first")
    engine = create_sqlite_engine(f"sqlite:///{db_path}")
    # The CLI deliberately never auto-migrates on every invocation (unlike the
    # API — see engram_api.runtime's own comment on that difference): opening
    # a space this build's schema has moved past is a real, common upgrade
    # scenario (a newer `engram` binary against an older ~/.engram), so it
    # must fail with guidance to run `engram init`, not run writes against a
    # schema missing columns this build's models assume (ADR-0026).
    require_current_schema(db_path, engine)
    registry = build_registry()
    kinds = build_kind_registry()
    store = SqliteEventStore(engine, registry)
    state = StateProjection(engine)
    search = SearchProjection(engine)
    proposals_projection = ProposalProjection(engine)

    bus = InProcessEventBus()
    projections = (state, search, proposals_projection)

    def _project(envelope: EventEnvelope) -> None:
        for projection in projections:
            if projection.handles(envelope.event_type):
                projection.apply(envelope)

    bus.subscribe(_project)

    repository = SqliteMemoryRepository(store, kinds)
    proposal_repository = SqliteProposalRepository(store)
    query = SqliteQueryEngine(engine)
    clock = SystemClock()
    proposals = ProposalCommandService(proposal_repository, repository, bus, clock, kinds, store)
    return Runtime(
        engine=engine,
        store=store,
        query_engine=query,
        state_projection=state,
        search_projection=search,
        proposals_projection=proposals_projection,
        commands=MemoryCommandService(repository, bus, clock, kinds, store),
        proposals=proposals,
        queries=MemoryQueryService(query),
        proposal_queries=ProposalQueryService(proposal_repository, query),
        search=SearchQueryService(query, clock, kinds),
        timeline=TimelineQueryService(query),
        history=HistoryQueryService(repository),
        exporter=ExportEngine(query, store, engine_version=__version__),
        importer=ImportEngine(store, registry, kinds, proposals),
    )
