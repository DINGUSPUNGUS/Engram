"""The API's composition root: the only place that names adapter implementations.

Mirrors ``engram_cli.runtime`` deliberately — both apps wire the same ports to the
same adapters, so behaviour cannot differ between the CLI and the REST surface
(ADR-0007). What differs is configuration and lifecycle, which is why each app owns
its own root rather than sharing one.

Built once per :func:`engram_api.main.create_app` and held on ``app.state``; the
dependency functions in :mod:`engram_api.dependencies` only read from it.
"""

from dataclasses import dataclass

from sqlalchemy.engine import Engine

from engram_api import __version__
from engram_api.config import EngramSettings
from engram_core.application.commands.memory_commands import MemoryCommandService
from engram_core.application.commands.proposal_commands import ProposalCommandService
from engram_core.application.queries.history_queries import HistoryQueryService
from engram_core.application.queries.memory_queries import MemoryQueryService
from engram_core.application.queries.proposal_queries import ProposalQueryService
from engram_core.application.queries.search_queries import SearchQueryService
from engram_core.application.queries.timeline_queries import TimelineQueryService
from engram_core.domain.events import build_registry
from engram_core.domain.kinds import build_kind_registry
from engram_events import EventEnvelope, EventRegistry, InProcessEventBus, SystemClock
from engram_export_git.exporter import ExportEngine
from engram_export_git.repo import GitVersionControl
from engram_storage_sqlite.event_store import SqliteEventStore, create_sqlite_engine
from engram_storage_sqlite.maintenance import rebuild_projections
from engram_storage_sqlite.migrate import upgrade_to_head
from engram_storage_sqlite.projections.proposals import ProposalProjection
from engram_storage_sqlite.projections.search import SearchProjection
from engram_storage_sqlite.projections.state import StateProjection
from engram_storage_sqlite.query_engine import SqliteQueryEngine
from engram_storage_sqlite.repositories import (
    SqliteMemoryRepository,
    SqliteProposalRepository,
)
from engram_storage_sqlite.status import SpaceStatus, space_status

_Projection = StateProjection | SearchProjection | ProposalProjection


@dataclass
class Runtime:
    """Every constructed service the routers may reach, and nothing else."""

    settings: EngramSettings
    engine: Engine
    registry: EventRegistry
    store: SqliteEventStore
    bus: InProcessEventBus
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
    git: GitVersionControl

    def rebuild(self) -> int:
        """Replay the log through every projection. Returns events applied."""
        return rebuild_projections(self.store, self._projections())

    def status(self) -> SpaceStatus:
        """Log totals and per-projection checkpoints (ADR-0021 ``/stats``)."""
        return space_status(self.engine, self._projections())

    def _projections(self) -> tuple[_Projection, ...]:
        return (self.state_projection, self.search_projection, self.proposals_projection)


def build_runtime(settings: EngramSettings) -> Runtime:
    """Wire ports to adapters for one API process.

    Unlike the CLI — which requires ``engram init`` first — the API migrates its
    database to head on construction. A server that cannot serve a fresh data
    directory is not local-first, and Alembic upgrades are idempotent.
    """
    db_path = settings.resolved_db_path
    db_path.parent.mkdir(parents=True, exist_ok=True)
    upgrade_to_head(db_path)

    engine = create_sqlite_engine(f"sqlite:///{db_path}")
    registry = build_registry()
    kinds = build_kind_registry()
    store = SqliteEventStore(engine, registry)

    state = StateProjection(engine)
    search_projection = SearchProjection(engine)
    proposals_projection = ProposalProjection(engine)
    projections = (state, search_projection, proposals_projection)

    bus = InProcessEventBus()

    def _project(envelope: EventEnvelope) -> None:
        for projection in projections:
            if projection.handles(envelope.event_type):
                projection.apply(envelope)

    bus.subscribe(_project)

    repository = SqliteMemoryRepository(store, kinds)
    proposal_repository = SqliteProposalRepository(store)
    query = SqliteQueryEngine(engine)
    clock = SystemClock()

    return Runtime(
        settings=settings,
        engine=engine,
        registry=registry,
        store=store,
        bus=bus,
        state_projection=state,
        search_projection=search_projection,
        proposals_projection=proposals_projection,
        commands=MemoryCommandService(repository, bus, clock, kinds),
        proposals=ProposalCommandService(proposal_repository, repository, bus, clock, kinds, store),
        queries=MemoryQueryService(query),
        proposal_queries=ProposalQueryService(proposal_repository, query),
        search=SearchQueryService(query, clock, kinds),
        timeline=TimelineQueryService(query),
        history=HistoryQueryService(repository),
        exporter=ExportEngine(query, store, engine_version=__version__),
        git=GitVersionControl(settings.resolved_export_repo),
    )
