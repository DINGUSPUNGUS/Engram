"""M5 pipeline stages: each stage against its contract, then the orchestrator
end-to-end with a deterministic provider — same inputs, same intents."""

import json
import re
from typing import TYPE_CHECKING, Any, cast

import pytest
from engram_intelligence.evaluators import FixtureMemoryQuery, fixture_read_model
from engram_intelligence.pipeline.assembly import DraftProposalAssembler
from engram_intelligence.pipeline.chunking import TurnChunker
from engram_intelligence.pipeline.conflicts import RuleConflictDetector
from engram_intelligence.pipeline.extraction import LLMEvidenceExtractor, parse_json_items
from engram_intelligence.pipeline.generation import LLMCandidateGenerator
from engram_intelligence.pipeline.orchestrator import IngestionPipeline
from engram_intelligence.pipeline.resolution import HeuristicEntityResolver
from engram_intelligence.pipeline.scoring_stage import PolicyImportanceScorer
from engram_intelligence.pipeline.trace import PipelineTrace, TracingProvider
from engram_intelligence.pipeline.types import (
    ConflictClass,
    MemoryCandidate,
    Transcript,
    Turn,
    TurnRole,
)
from engram_intelligence.prompts.registry import load_library
from engram_intelligence.provider import FakeProvider

from engram_core.application.commands import drafts as d
from engram_core.domain import scoring
from engram_core.domain.kinds import build_kind_registry
from engram_core.domain.values import MemoryKind, new_proposal_id
from engram_events import Provenance

if TYPE_CHECKING:
    from engram_core.application.commands.proposal_commands import ProposalCommandService

KINDS = build_kind_registry()
PROMPTS = load_library()

_QUOTE_1 = "my colleague Sarah Chen is joining the kahnya project next week"
_QUOTE_2 = "Her work email is sarah.chen@acme.io"

_EXTRACTION_RESPONSE = json.dumps(
    [
        {"quote": _QUOTE_1, "evidence_type": "quote", "reason": "a person enters the graph"},
        {"quote": _QUOTE_2, "evidence_type": "quote", "reason": "contact detail"},
        {"quote": "this sentence never happened", "reason": "hallucinated"},
    ]
)
_GENERATION_RESPONSE = json.dumps(
    [
        {
            "kind": "person",
            "title": "Sarah Chen",
            "content": "Colleague joining the kahnya project.",
            "attributes": {"full_name": "Sarah Chen", "aliases": ["SC"]},
            "evidence_quotes": [_QUOTE_1],
            "links": [],
        },
        {
            "kind": "contact",
            "title": "Sarah Chen's work email",
            "content": "",
            "attributes": {"channel": "email", "value": "sarah.chen@acme.io", "label": "work"},
            "evidence_quotes": [_QUOTE_2],
            "links": [{"relation": "owned_by", "target": "candidate:0"}],
        },
        {
            "kind": "spaceship",
            "title": "nonsense",
            "attributes": {},
            "evidence_quotes": [_QUOTE_1],
        },
        {
            "kind": "fact",
            "title": "unsupported claim",
            "attributes": {"statement": "no evidence cites this"},
            "evidence_quotes": [],
        },
    ]
)


def fake_provider() -> FakeProvider:
    return FakeProvider(
        responses={
            "evidence-extraction": _EXTRACTION_RESPONSE,
            "candidate-generation": _GENERATION_RESPONSE,
        }
    )


def transcript() -> Transcript:
    return Transcript(
        source=Provenance(actor="claude", session_id="s-42"),
        turns=(
            Turn(TurnRole.USER, f"Quick intro — {_QUOTE_1}. {_QUOTE_2}."),
            Turn(TurnRole.ASSISTANT, "Noted — Sarah Chen (SC), sarah.chen@acme.io."),
        ),
        transcript_id="t-1",
    )


class RecordingProposals:
    """Stands in for ProposalCommandService: records, validates, mints an id."""

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def open_proposal(
        self,
        title: str,
        description: str,
        proposed_events: list[dict[str, object]],
        provenance: Provenance,
    ) -> Any:
        d.parse_all(proposed_events)  # the real service validates too
        self.calls.append(
            {
                "title": title,
                "description": description,
                "drafts": proposed_events,
                "provenance": provenance,
            }
        )
        return new_proposal_id()


def build(
    query: FixtureMemoryQuery | None = None,
) -> tuple[IngestionPipeline, RecordingProposals, PipelineTrace]:
    trace = PipelineTrace()
    provider = TracingProvider(fake_provider(), trace)
    trace.configure(provider="fake")
    q = query if query is not None else FixtureMemoryQuery([])
    proposals = RecordingProposals()
    pipeline = IngestionPipeline(
        chunker=TurnChunker(),
        extractor=LLMEvidenceExtractor(provider, PROMPTS, trace),
        resolver=HeuristicEntityResolver(q),
        generator=LLMCandidateGenerator(provider, PROMPTS, KINDS, trace),
        conflict_detector=RuleConflictDetector(q),
        scorer=PolicyImportanceScorer(),
        assembler=DraftProposalAssembler(q, KINDS, trace),
        proposals=cast("ProposalCommandService", proposals),
        trace=trace,
    )
    return pipeline, proposals, trace


# ---------------------------------------------------------------------------
# Stage units
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_prompt_library_ships_loaded_and_versioned() -> None:
    assert PROMPTS.get("evidence-extraction").stage == "evidence_extraction"
    assert PROMPTS.get("candidate-generation").stage == "candidate_generation"
    # v2 (object-wrapped output for small local models) is the shipped latest;
    # v1 remains loadable forever (ADR-0013).
    assert PROMPTS.get("evidence-extraction").qualified_name == "evidence-extraction@2"
    assert PROMPTS.get("evidence-extraction", version=1).qualified_name == "evidence-extraction@1"


@pytest.mark.unit
def test_chunker_covers_every_turn_and_never_splits_one() -> None:
    long_turns = tuple(
        Turn(TurnRole.USER if i % 2 == 0 else TurnRole.ASSISTANT, f"turn {i}: " + "x" * 700)
        for i in range(6)
    )
    chunks = TurnChunker(budget_chars=1600).chunk(
        Transcript(source=Provenance(actor="user"), turns=long_turns)
    )
    covered = [t for chunk in chunks for t in range(chunk.turn_start, chunk.turn_end + 1)]
    assert covered == list(range(6))
    assert all(chunk.text for chunk in chunks)
    assert len(chunks) > 1


@pytest.mark.unit
def test_json_item_parsing_tolerates_the_object_wrapper() -> None:
    assert parse_json_items('[{"a": 1}]') == [{"a": 1}]
    assert parse_json_items('{"items": [{"a": 1}]}') == [{"a": 1}]
    assert parse_json_items('{"quote": "x"}') == [{"quote": "x"}]
    with pytest.raises(ValueError):
        parse_json_items('"just a string"')


@pytest.mark.unit
def test_extractor_keeps_only_verbatim_quotes_and_explains_drops() -> None:
    trace = PipelineTrace()
    extractor = LLMEvidenceExtractor(fake_provider(), PROMPTS, trace)
    chunks = TurnChunker().chunk(transcript())
    evidence = extractor.extract(chunks)
    assert [e.quote for e in evidence] == [_QUOTE_1, _QUOTE_2]
    assert any("non-verbatim" in note for note in trace.notes)


@pytest.mark.unit
def test_generator_enforces_the_stage_law() -> None:
    trace = PipelineTrace()
    generator = LLMCandidateGenerator(fake_provider(), PROMPTS, KINDS, trace)
    chunks = TurnChunker().chunk(transcript())
    extractor = LLMEvidenceExtractor(fake_provider(), PROMPTS, PipelineTrace())
    evidence = extractor.extract(chunks)
    candidates = generator.generate(chunks, evidence, ())
    # The spaceship (unknown kind) and the unsupported fact never leave the stage.
    assert [c.kind for c in candidates] == [MemoryKind.PERSON, MemoryKind.CONTACT]
    assert candidates[1].links[0].target_candidate_index == 0
    assert all(c.evidence for c in candidates)
    assert any("unknown kind" in note for note in trace.notes)
    assert any("no verbatim evidence" in note for note in trace.notes)


@pytest.mark.unit
def test_resolver_matches_aliases_and_never_guesses() -> None:
    sarah = fixture_read_model(
        "t", 0, {"kind": "person", "attributes": {"full_name": "Sarah Chen", "aliases": ["SC"]}}
    )
    unrelated = fixture_read_model(
        "t", 1, {"kind": "person", "attributes": {"full_name": "Nobody Mentioned"}}
    )
    resolver = HeuristicEntityResolver(FixtureMemoryQuery([sarah, unrelated]))
    mentions = resolver.resolve(TurnChunker().chunk(transcript()), ())
    assert [m.resolved_id for m in mentions] == [sarah.id]


@pytest.mark.unit
def test_conflict_rules_duplicate_contradiction_and_coexistence() -> None:
    existing_contact = fixture_read_model(
        "t",
        0,
        {"kind": "contact", "attributes": {"channel": "email", "value": "sarah.chen@acme.io"}},
    )
    existing_pref = fixture_read_model(
        "t",
        1,
        {
            "kind": "preference",
            "title": "Prefers light mode",
            "attributes": {"polarity": "prefers", "context": "dashboard theme"},
        },
    )
    detector = RuleConflictDetector(FixtureMemoryQuery([existing_contact, existing_pref]))
    candidates = [
        MemoryCandidate(
            kind=MemoryKind.CONTACT,
            title="work email",
            content="",
            attributes={"channel": "email", "value": "Sarah.Chen@acme.io"},
        ),
        MemoryCandidate(
            kind=MemoryKind.PREFERENCE,
            title="Prefers dark mode",
            content="",
            attributes={"polarity": "prefers", "context": "dashboard theme"},
        ),
        MemoryCandidate(
            kind=MemoryKind.PREFERENCE,
            title="Light print stylesheets",
            content="",
            attributes={"polarity": "prefers", "context": "print stylesheets"},
        ),
    ]
    reports = detector.detect(candidates)
    by_index = {r.candidate_index: r for r in reports}
    assert by_index[0].conflict_class is ConflictClass.DUPLICATE
    assert by_index[1].conflict_class is ConflictClass.CONTRADICTION
    assert 2 not in by_index  # different context coexists (memory-model.md §8)


@pytest.mark.unit
def test_scorer_applies_policy_and_assistant_prior() -> None:
    candidate = MemoryCandidate(
        kind=MemoryKind.PERSON, title="x", content="", attributes={"full_name": "x"}
    )
    (scored,) = PolicyImportanceScorer().score([candidate], [])
    assert scored.importance == scoring.candidate_importance(MemoryKind.PERSON)
    assert scored.candidate.confidence_prior == scoring.CONFIDENCE_PRIOR_ASSISTANT_INFERRED
    assert scored.rationale is not None and "kind base" in scored.rationale


# ---------------------------------------------------------------------------
# End-to-end (fake provider): the whole point
# ---------------------------------------------------------------------------


def _ops(drafts: list[dict[str, object]]) -> list[str]:
    return [str(record["op"]) for record in drafts]


@pytest.mark.unit
def test_ingest_opens_one_proposal_and_never_touches_memory() -> None:
    pipeline, proposals, _ = build()
    outcome = pipeline.ingest(transcript())
    assert outcome.proposal_id is not None
    assert outcome.candidate_count == 2
    assert len(proposals.calls) == 1
    ops = _ops(proposals.calls[0]["drafts"])
    assert ops == [
        "create_memory",  # Sarah Chen
        "add_evidence",
        "create_memory",  # her email
        "add_evidence",
        "link_memories",  # contact owned_by person
    ]


@pytest.mark.unit
def test_ingest_reconciles_duplicates_instead_of_recreating() -> None:
    existing = fixture_read_model(
        "dup",
        0,
        {
            "kind": "contact",
            "attributes": {"channel": "email", "value": "sarah.chen@acme.io", "label": "old"},
        },
    )
    pipeline, proposals, _ = build(FixtureMemoryQuery([existing]))
    outcome = pipeline.ingest(transcript())
    assert outcome.proposal_id is not None
    drafts = proposals.calls[0]["drafts"]
    ops = _ops(drafts)
    # THE rule, extended from M4: the duplicate contact updates the existing
    # memory (label old -> work) — a second create_memory never appears for it.
    assert ops.count("create_memory") == 1  # only the person is new
    assert "update_attributes" in ops
    update = next(r for r in drafts if r["op"] == "update_attributes")
    assert update["memory_id"] == str(existing.id)
    assert update["changes"] == {"label": "work"}
    assert update["base_version"] == existing.version
    # The owned_by link re-points at the reconciled existing memory.
    link = next(r for r in drafts if r["op"] == "link_memories")
    assert link["source_id"] == str(existing.id)


@pytest.mark.unit
def test_ingest_proposes_contradiction_never_resolves_it() -> None:
    trace = PipelineTrace()
    provider = FakeProvider(
        responses={
            "evidence-extraction": json.dumps(
                [{"quote": "I actually prefer dark mode now", "reason": "preference change"}]
            ),
            "candidate-generation": json.dumps(
                [
                    {
                        "kind": "preference",
                        "title": "Prefers dark mode",
                        "content": "",
                        "attributes": {"polarity": "prefers", "context": "dashboard theme"},
                        "evidence_quotes": ["I actually prefer dark mode now"],
                    }
                ]
            ),
        }
    )
    existing = fixture_read_model(
        "pref",
        0,
        {
            "kind": "preference",
            "title": "Prefers light mode",
            "attributes": {"polarity": "prefers", "context": "dashboard theme"},
        },
    )
    query = FixtureMemoryQuery([existing])
    proposals = RecordingProposals()
    pipeline = IngestionPipeline(
        chunker=TurnChunker(),
        extractor=LLMEvidenceExtractor(provider, PROMPTS, trace),
        resolver=HeuristicEntityResolver(query),
        generator=LLMCandidateGenerator(provider, PROMPTS, KINDS, trace),
        conflict_detector=RuleConflictDetector(query),
        scorer=PolicyImportanceScorer(),
        assembler=DraftProposalAssembler(query, KINDS, trace),
        proposals=cast("ProposalCommandService", proposals),
        trace=trace,
    )
    outcome = pipeline.ingest(
        Transcript(
            source=Provenance(actor="claude"),
            turns=(Turn(TurnRole.USER, "I actually prefer dark mode now."),),
        )
    )
    assert outcome.conflict_count == 1
    drafts = proposals.calls[0]["drafts"]
    ops = _ops(drafts)
    assert "create_memory" in ops  # the new preference is created…
    assert "contradict_memory" in ops  # …the clash is STATED…
    contradict = next(r for r in drafts if r["op"] == "contradict_memory")
    assert contradict["memory_id"] == str(existing.id)
    assert contradict["base_version"] == existing.version
    supersede = next(r for r in drafts if r["op"] == "link_memories")
    assert supersede["relation"] == "supersedes"  # …and supersession is PROPOSED
    assert "update_attributes" not in ops  # never silently resolved


@pytest.mark.unit
def test_identical_runs_produce_identical_intents_and_provenance() -> None:
    def run() -> tuple[str, str]:
        pipeline, proposals, _ = build()
        pipeline.ingest(transcript())
        call = proposals.calls[0]
        blob = json.dumps(call["drafts"], sort_keys=True) + call["description"]
        detail = call["provenance"].detail
        assert detail is not None
        return _normalize_ids(blob), detail

    first_drafts, first_detail = run()
    second_drafts, second_detail = run()
    assert first_drafts == second_drafts  # identical intents (ids normalized)
    assert first_detail == second_detail  # identical explanation, byte for byte

    metadata = json.loads(first_detail)
    assert metadata["pipeline"] == "ingestion/1"
    assert metadata["prompts"] == ["candidate-generation@2", "evidence-extraction@2"]
    assert metadata["counts"]["candidates"] == 2
    assert metadata["configuration"]["provider"] == "fake"
    assert len(metadata["llm_calls"]) == 2  # one extraction chunk + one generation
    assert metadata["notes"]  # the dropped hallucination is explained


def _normalize_ids(text: str) -> str:
    return re.sub(r"[0-9a-f]{8}-?[0-9a-f]{4}-?[0-9a-f]{4}-?[0-9a-f]{4}-?[0-9a-f]{12}", "ID", text)


@pytest.mark.unit
def test_empty_results_are_good_results() -> None:
    trace = PipelineTrace()
    provider = FakeProvider(default="[]")
    proposals = RecordingProposals()
    query = FixtureMemoryQuery([])
    pipeline = IngestionPipeline(
        chunker=TurnChunker(),
        extractor=LLMEvidenceExtractor(provider, PROMPTS, trace),
        resolver=HeuristicEntityResolver(query),
        generator=LLMCandidateGenerator(provider, PROMPTS, KINDS, trace),
        conflict_detector=RuleConflictDetector(query),
        scorer=PolicyImportanceScorer(),
        assembler=DraftProposalAssembler(query, KINDS, trace),
        proposals=cast("ProposalCommandService", proposals),
        trace=trace,
    )
    outcome = pipeline.ingest(
        Transcript(source=Provenance(actor="claude"), turns=(Turn(TurnRole.USER, "hi"),))
    )
    assert outcome.proposal_id is None
    assert proposals.calls == []  # side-effect free until something qualifies
    assert "no durable evidence found" in outcome.skipped_reasons
