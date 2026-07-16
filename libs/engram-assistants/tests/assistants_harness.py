"""Shared harness: a real space (aggregate → event store → projections) plus the
assistant gateway wired over it, with a deterministic fake LLM provider — the
same composition shape the CLI runtime uses."""

import json
from dataclasses import dataclass
from pathlib import Path

from engram_assistants.gateway import AssistantGateway
from engram_intelligence.pipeline.assembly import DraftProposalAssembler
from engram_intelligence.pipeline.chunking import TurnChunker
from engram_intelligence.pipeline.conflicts import RuleConflictDetector
from engram_intelligence.pipeline.extraction import LLMEvidenceExtractor
from engram_intelligence.pipeline.generation import LLMCandidateGenerator
from engram_intelligence.pipeline.orchestrator import IngestionPipeline
from engram_intelligence.pipeline.resolution import HeuristicEntityResolver
from engram_intelligence.pipeline.scoring_stage import PolicyImportanceScorer
from engram_intelligence.pipeline.trace import PipelineTrace, TracingProvider
from engram_intelligence.prompts.registry import load_library
from engram_intelligence.provider import FakeProvider

from engram_core.application.commands.memory_commands import MemoryCommandService
from engram_core.application.commands.proposal_commands import ProposalCommandService
from engram_core.application.queries.memory_queries import MemoryQueryService
from engram_core.application.queries.proposal_queries import ProposalQueryService
from engram_core.application.queries.search_queries import SearchQueryService
from engram_core.application.queries.timeline_queries import TimelineQueryService
from engram_core.domain.events import build_registry
from engram_core.domain.kinds import build_kind_registry
from engram_events import EventEnvelope, InProcessEventBus, Provenance, SystemClock
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

QUOTE = "my colleague Sarah Chen is joining the kahnya project"

CONVERSATION = [
    {"role": "user", "content": f"Quick intro — {QUOTE}."},
    {"role": "assistant", "content": "Great, noted."},
]

FAKE_RESPONSES = {
    "evidence-extraction": json.dumps(
        {
            "evidence": [
                {"quote": QUOTE, "evidence_type": "quote", "reason": "new person"}
            ]
        }
    ),
    "candidate-generation": json.dumps(
        {
            "candidates": [
                {
                    "kind": "person",
                    "title": "Sarah Chen",
                    "content": "Colleague on the kahnya project.",
                    "attributes": {"full_name": "Sarah Chen"},
                    "evidence_quotes": [QUOTE],
                    "links": [],
                }
            ]
        }
    ),
}


@dataclass
class AssistantSpace:
    """Everything a gateway test needs, over one scratch database."""

    store: SqliteEventStore
    commands: MemoryCommandService
    proposals: ProposalCommandService
    proposal_queries: ProposalQueryService
    query: SqliteQueryEngine
    gateway: AssistantGateway
    state: StateProjection
    search: SearchProjection
    proposal_rows: ProposalProjection

    def rebuild(self) -> int:
        return rebuild_projections(self.store, [self.state, self.search, self.proposal_rows])


def build_assistant_space(db_path: Path) -> AssistantSpace:
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
    commands = MemoryCommandService(repository, bus, clock, kinds)
    proposals = ProposalCommandService(proposal_repository, repository, bus, clock, kinds, store)

    trace = PipelineTrace()
    trace.configure(provider="fake")
    provider = TracingProvider(FakeProvider(FAKE_RESPONSES), trace)
    prompts = load_library()
    pipeline = IngestionPipeline(
        chunker=TurnChunker(),
        extractor=LLMEvidenceExtractor(provider, prompts, trace),
        resolver=HeuristicEntityResolver(query),
        generator=LLMCandidateGenerator(provider, prompts, kinds, trace),
        conflict_detector=RuleConflictDetector(query),
        scorer=PolicyImportanceScorer(),
        assembler=DraftProposalAssembler(query, kinds, trace),
        proposals=proposals,
        trace=trace,
    )
    gateway = AssistantGateway(
        search=SearchQueryService(query, clock, kinds),
        queries=MemoryQueryService(query),
        timeline=TimelineQueryService(query),
        commands=commands,
        pipeline=pipeline,
        proposals=ProposalQueryService(proposal_repository, query),
    )
    return AssistantSpace(
        store=store,
        commands=commands,
        proposals=proposals,
        proposal_queries=ProposalQueryService(proposal_repository, query),
        query=query,
        gateway=gateway,
        state=state,
        search=search,
        proposal_rows=proposal_rows,
    )
