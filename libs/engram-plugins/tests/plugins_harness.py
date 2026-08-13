"""Shared harness: a real space (aggregate → event store → projections) plus
the plugin gateway/registry wired over it — the same composition shape the CLI
runtime uses (mirrors ``engram_assistants``' ``assistants_harness.py``)."""

from dataclasses import dataclass
from pathlib import Path

from engram_core.application.commands.memory_commands import MemoryCommandService
from engram_core.application.commands.proposal_commands import ProposalCommandService
from engram_core.application.dto import CreateMemoryInput
from engram_core.application.queries.memory_queries import MemoryQueryService
from engram_core.application.queries.proposal_queries import ProposalQueryService
from engram_core.application.queries.search_queries import SearchQueryService
from engram_core.application.queries.timeline_queries import TimelineQueryService
from engram_core.domain.events import build_registry
from engram_core.domain.kinds import build_kind_registry
from engram_core.domain.values import MemoryId, MemoryKind, Visibility
from engram_events import EventEnvelope, InProcessEventBus, Provenance, SystemClock
from engram_plugins.gateway import PluginGateway
from engram_plugins.registry import PluginRegistry
from engram_storage_sqlite.event_store import SqliteEventStore, create_sqlite_engine
from engram_storage_sqlite.maintenance import rebuild_projections
from engram_storage_sqlite.migrate import upgrade_to_head
from engram_storage_sqlite.projections.proposals import ProposalProjection
from engram_storage_sqlite.projections.search import SearchProjection
from engram_storage_sqlite.projections.state import StateProjection
from engram_storage_sqlite.query_engine import SqliteQueryEngine
from engram_storage_sqlite.repositories import SqliteMemoryRepository, SqliteProposalRepository

USER = Provenance(actor="user", detail="test")


@dataclass
class PluginSpace:
    """Everything a plugin test needs, over one scratch database."""

    store: SqliteEventStore
    commands: MemoryCommandService
    proposals: ProposalCommandService
    proposal_queries: ProposalQueryService
    memory_queries: MemoryQueryService
    query: SqliteQueryEngine
    gateway: PluginGateway
    registry: PluginRegistry
    state: StateProjection
    search: SearchProjection
    proposal_rows: ProposalProjection

    def rebuild(self) -> int:
        return rebuild_projections(self.store, [self.state, self.search, self.proposal_rows])

    def add_memory(
        self,
        kind: MemoryKind,
        title: str,
        content: str,
        *,
        visibility: Visibility | None = None,
        **attributes: object,
    ) -> MemoryId:
        return self.commands.create_memory(
            CreateMemoryInput(
                kind=kind,
                title=title,
                content=content,
                attributes=attributes,
                visibility=visibility,
            ),
            USER,
        )


def build_plugin_space(db_path: Path) -> PluginSpace:
    upgrade_to_head(db_path)
    engine = create_sqlite_engine(f"sqlite:///{db_path}")
    registry = build_registry()
    kinds = build_kind_registry()
    store = SqliteEventStore(engine, registry)
    state = StateProjection(engine)
    search = SearchProjection(engine)
    proposal_rows = ProposalProjection(engine)
    bus = InProcessEventBus()
    projections = (state, search, proposal_rows)

    def _project(envelope: EventEnvelope) -> None:
        for projection in projections:
            if projection.handles(envelope.event_type):
                projection.apply(envelope)

    bus.subscribe(_project)
    repository = SqliteMemoryRepository(store, kinds)
    proposal_repository = SqliteProposalRepository(store)
    clock = SystemClock()
    query = SqliteQueryEngine(engine)
    commands = MemoryCommandService(repository, bus, clock, kinds, store)
    proposals = ProposalCommandService(proposal_repository, repository, bus, clock, kinds, store)
    memory_queries = MemoryQueryService(query)

    gateway = PluginGateway(
        queries=memory_queries,
        search=SearchQueryService(query, clock, kinds),
        timeline=TimelineQueryService(query),
        commands=commands,
        proposals=proposals,
    )
    return PluginSpace(
        store=store,
        commands=commands,
        proposals=proposals,
        proposal_queries=ProposalQueryService(proposal_repository, query),
        memory_queries=memory_queries,
        query=query,
        gateway=gateway,
        registry=PluginRegistry(),
        state=state,
        search=search,
        proposal_rows=proposal_rows,
    )
