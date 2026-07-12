"""The CLI's composition root: the only place that names adapter implementations."""

from dataclasses import dataclass

from engram_cli.config import CliSettings
from engram_core.application.commands.memory_commands import MemoryCommandService
from engram_core.application.queries.memory_queries import MemoryQueryService
from engram_core.application.queries.timeline_queries import TimelineQueryService
from engram_core.domain.errors import NotFoundError
from engram_core.domain.events import build_registry
from engram_core.domain.kinds import build_kind_registry
from engram_events import EventEnvelope, InProcessEventBus, SystemClock
from engram_storage_sqlite.event_store import SqliteEventStore, create_sqlite_engine
from engram_storage_sqlite.maintenance import rebuild_projections
from engram_storage_sqlite.projections.state import StateProjection
from engram_storage_sqlite.queries import SqliteMemoryQuery
from engram_storage_sqlite.repositories import SqliteMemoryRepository


@dataclass
class Runtime:
    store: SqliteEventStore
    state_projection: StateProjection
    commands: MemoryCommandService
    queries: MemoryQueryService
    timeline: TimelineQueryService

    def rebuild(self) -> int:
        return rebuild_projections(self.store, [self.state_projection])


def build_runtime(settings: CliSettings) -> Runtime:
    db_path = settings.resolved_db_path
    if not db_path.exists():
        raise NotFoundError(f"no engram database at {db_path} — run `engram init` first")
    engine = create_sqlite_engine(f"sqlite:///{db_path}")
    registry = build_registry()
    kinds = build_kind_registry()
    store = SqliteEventStore(engine, registry)
    state = StateProjection(engine)

    bus = InProcessEventBus()

    def _project(envelope: EventEnvelope) -> None:
        if state.handles(envelope.event_type):
            state.apply(envelope)

    bus.subscribe(_project)

    repository = SqliteMemoryRepository(store, kinds)
    query = SqliteMemoryQuery(engine)
    return Runtime(
        store=store,
        state_projection=state,
        commands=MemoryCommandService(repository, bus, SystemClock(), kinds),
        queries=MemoryQueryService(query),
        timeline=TimelineQueryService(query),
    )
