"""Shared test harness: the full write path over a migrated scratch database.

Tests here exercise the export/import engines against the *real* stack (aggregate →
event store → projections), mirroring the CLI runtime's composition. Storage is a
test-only dependency: the engines themselves speak ports.
"""

from dataclasses import dataclass
from pathlib import Path

from sqlalchemy.engine import Engine

from engram_core.application.commands.memory_commands import MemoryCommandService
from engram_core.application.commands.proposal_commands import ProposalCommandService
from engram_core.application.dto import CreateMemoryInput, EditMemoryInput
from engram_core.domain.events import build_registry
from engram_core.domain.kinds import build_kind_registry
from engram_core.domain.values import (
    EvidenceRef,
    EvidenceType,
    LinkRelation,
    MemoryId,
    MemoryKind,
)
from engram_events import EventEnvelope, InProcessEventBus, Provenance, SystemClock
from engram_export_git.exporter import ExportEngine
from engram_export_git.importer import ImportEngine
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

USER = Provenance(actor="user", detail="test")
ASSISTANT = Provenance(actor="claude", session_id="s42")


@dataclass
class Space:
    """The CLI runtime's shape, wired for one scratch database."""

    engine: Engine
    store: SqliteEventStore
    commands: MemoryCommandService
    proposals: ProposalCommandService
    query: SqliteQueryEngine
    exporter: ExportEngine
    importer: ImportEngine
    state: StateProjection
    search: SearchProjection
    proposal_rows: ProposalProjection

    def rebuild(self) -> int:
        return rebuild_projections(self.store, [self.state, self.search, self.proposal_rows])


def build_space(db_path: Path) -> Space:
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
    proposals = ProposalCommandService(proposal_repository, repository, bus, clock, kinds, store)
    return Space(
        engine=engine,
        store=store,
        commands=MemoryCommandService(repository, bus, clock, kinds),
        proposals=proposals,
        query=query,
        exporter=ExportEngine(query, store, engine_version="test"),
        importer=ImportEngine(store, registry, kinds, proposals),
        state=state,
        search=search,
        proposal_rows=proposal_rows,
    )


def seed_rich_space(space: Space) -> dict[str, MemoryId]:
    """A space that exercises every M3 concern: kinds, tags, edits, archive,
    links, evidence, a relationship object, and mixed provenance."""
    project_id = space.commands.create_memory(
        CreateMemoryInput(
            kind=MemoryKind.PROJECT,
            title="engram",
            content="the memory engine — event-sourced, git-native",
            attributes={"name": "engram", "status": "active"},
            tags=("oss", "infra"),
        ),
        USER,
    )
    fact_id = space.commands.create_memory(
        CreateMemoryInput(
            kind=MemoryKind.FACT,
            title='User prefers "dark" mode — always',
            content="Unicode survives: émigré, 記憶, 🧠.\n\nMultiple paragraphs too.",
            attributes={"statement": "User prefers dark mode"},
            tags=("ui",),
        ),
        ASSISTANT,
    )
    person_id = space.commands.create_memory(
        CreateMemoryInput(
            kind=MemoryKind.PERSON,
            title="Jude",
            content="",
            attributes={"full_name": "Jude N.", "aliases": ["dinguspungus"]},
        ),
        USER,
    )
    relationship_id = space.commands.create_memory(
        CreateMemoryInput(
            kind=MemoryKind.RELATIONSHIP,
            title="Jude maintains engram",
            content="",
            attributes={
                "subject_id": str(person_id),
                "predicate": "maintains",
                "object_id": str(project_id),
            },
        ),
        USER,
    )
    archived_id = space.commands.create_memory(
        CreateMemoryInput(
            kind=MemoryKind.FACT,
            title="Old coffee fact",
            content="",
            attributes={"statement": "drinks coffee"},
        ),
        USER,
    )
    space.commands.archive_memory(archived_id, "superseded", USER)
    version = space.query.get(project_id).version
    space.commands.edit_memory(
        project_id,
        EditMemoryInput(expected_version=version, title="engram (the memory engine)"),
        USER,
    )
    space.commands.link_memories(fact_id, project_id, LinkRelation.ABOUT, USER)
    space.commands.link_memories(person_id, project_id, LinkRelation.INVOLVES, ASSISTANT)
    space.commands.add_evidence(
        fact_id,
        EvidenceRef(EvidenceType.QUOTE, "let's always use dark mode", note="from chat"),
        USER,
    )
    space.commands.record_access(fact_id, "recall demo", ASSISTANT)
    return {
        "project": project_id,
        "fact": fact_id,
        "person": person_id,
        "relationship": relationship_id,
        "archived": archived_id,
    }
