"""Stage evaluators for the golden suite (ADR-0014).

Two families, exactly as the gate prescribes:

- **Deterministic evaluators** (chunking, entity resolution, conflict rules) run
  in CI on every change. They evaluate each stage on *ground-truth inputs* — the
  expected candidates and fixture state a case declares — so a regression is
  localizable to the stage that caused it, never masked by an upstream model.
- **LLM evaluators** (extraction, candidate generation) run when a provider is
  configured; their scores are comparable only within one provider+model
  configuration, which the committed baseline records.
"""

import statistics
import uuid
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime

from engram_core.application.dto import MemoryReadModel, Page, TimelineEntry
from engram_core.domain.errors import NotFoundError
from engram_core.domain.kinds import KindRegistry
from engram_core.domain.values import MemoryId, MemoryKind
from engram_intelligence.evals import EvalCase, EvalScore, StageEvaluator
from engram_intelligence.pipeline.chunking import TurnChunker
from engram_intelligence.pipeline.conflicts import RuleConflictDetector
from engram_intelligence.pipeline.extraction import LLMEvidenceExtractor
from engram_intelligence.pipeline.generation import LLMCandidateGenerator
from engram_intelligence.pipeline.resolution import HeuristicEntityResolver
from engram_intelligence.pipeline.trace import PipelineTrace
from engram_intelligence.pipeline.types import MemoryCandidate
from engram_intelligence.prompts.registry import PromptRegistry
from engram_intelligence.provider import LLMProvider

_FIXTURE_NAMESPACE = uuid.uuid5(uuid.NAMESPACE_URL, "engram:eval-fixtures")


def fixture_id(case_id: str, index: int) -> MemoryId:
    """Stable, deterministic id for a fixture memory (uuid5 of case+index)."""
    return MemoryId(uuid.uuid5(_FIXTURE_NAMESPACE, f"{case_id}:{index}"))


def fixture_read_model(case_id: str, index: int, spec: Mapping[str, object]) -> MemoryReadModel:
    """Build a read model from a golden case's ``existing:`` entry."""
    kind = MemoryKind(str(spec["kind"]))
    raw_attributes = spec.get("attributes")
    attributes = dict(raw_attributes) if isinstance(raw_attributes, Mapping) else {}
    title = str(
        spec.get("title")
        or attributes.get("name")
        or attributes.get("full_name")
        or attributes.get("statement")
        or kind.value
    )
    anchor = datetime(2026, 1, 1, tzinfo=UTC)
    return MemoryReadModel(
        id=fixture_id(case_id, index),
        kind=kind,
        slug=f"fixture-{case_id}-{index}",
        title=title,
        content=str(spec.get("content") or ""),
        attributes=attributes,
        tags=(),
        links=(),
        evidence=(),
        confidence=0.9,
        effective_confidence=0.9,
        stale=False,
        last_confirmed_at=None,
        lifetime_policy="standard",
        lifetime_until=None,
        visibility="shared",
        allowed_actors=(),
        pinned=False,
        user_weight=None,
        access_count=0,
        last_accessed_at=None,
        retention_score=0.5,
        archived=False,
        created_by="user",
        created_at=anchor,
        updated_at=anchor,
        version=1,
    )


class FixtureMemoryQuery:
    """A ``MemoryQuery`` over in-memory fixtures (also handy in tests)."""

    def __init__(self, models: Sequence[MemoryReadModel]) -> None:
        self._models = list(models)

    def get(self, memory_id: MemoryId) -> MemoryReadModel:
        for model in self._models:
            if model.id == memory_id:
                return model
        raise NotFoundError(f"no such memory: {memory_id}")

    def list_memories(
        self,
        *,
        kind: MemoryKind | None = None,
        tag: str | None = None,
        include_archived: bool = False,
        include_stale: bool = True,
        cursor: str | None = None,
        limit: int = 50,
    ) -> Page[MemoryReadModel]:
        items = [m for m in self._models if kind is None or m.kind is kind]
        return Page(items=tuple(items), next_cursor=None)

    def timeline(self, memory_id: MemoryId) -> Sequence[TimelineEntry]:
        raise NotFoundError(f"fixtures have no timelines: {memory_id}")


def _existing_fixtures(case: EvalCase) -> list[MemoryReadModel]:
    raw = case.expected.get("existing")
    entries = raw if isinstance(raw, list) else []
    return [
        fixture_read_model(case.case_id, index, spec)
        for index, spec in enumerate(entries)
        if isinstance(spec, dict)
    ]


def _expected_candidates(case: EvalCase, kinds: KindRegistry) -> list[MemoryCandidate]:
    """Ground-truth candidates from the Expected block — downstream stages are
    evaluated on these, not on an upstream model's output."""
    raw = case.expected.get("candidates")
    entries = raw if isinstance(raw, list) else []
    candidates: list[MemoryCandidate] = []
    for spec in entries:
        if not isinstance(spec, dict):
            continue
        kind = MemoryKind(str(spec["kind"]))
        attributes = dict(spec.get("attributes") or {})
        title = str(
            spec.get("title")
            or attributes.get("name")
            or attributes.get("full_name")
            or attributes.get("statement")
            or spec.get("content_mentions")
            or kind.value
        )
        candidates.append(
            MemoryCandidate(
                kind=kind,
                title=title,
                content=str(spec.get("content_mentions") or ""),
                attributes=attributes,
            )
        )
    return candidates


# ---------------------------------------------------------------------------
# Deterministic evaluators (CI, always)
# ---------------------------------------------------------------------------


class ChunkingEvaluator:
    """Invariants: every turn lands in exactly one chunk, no chunk is empty."""

    @property
    def stage(self) -> str:
        return "chunking"

    def evaluate(self, case: EvalCase) -> EvalScore:
        chunks = TurnChunker().chunk(case.transcript)
        covered: list[int] = []
        for chunk in chunks:
            covered.extend(range(chunk.turn_start, chunk.turn_end + 1))
        complete = covered == list(range(len(case.transcript.turns)))
        non_empty = all(chunk.text.strip() for chunk in chunks)
        passed = complete and non_empty
        return EvalScore(
            case_id=case.case_id,
            stage=self.stage,
            score=1.0 if passed else 0.0,
            passed=passed,
            detail=f"{len(chunks)} chunk(s), coverage={'ok' if complete else 'BROKEN'}",
        )


class EntityResolutionEvaluator:
    """Against fixture state: resolve what is present, never invent an id."""

    @property
    def stage(self) -> str:
        return "entity_resolution"

    def evaluate(self, case: EvalCase) -> EvalScore:
        fixtures = _existing_fixtures(case)
        resolver = HeuristicEntityResolver(FixtureMemoryQuery(fixtures))
        chunks = TurnChunker().chunk(case.transcript)
        mentions = resolver.resolve(chunks, ())
        fixture_ids = {model.id for model in fixtures}
        no_inventions = all(
            mention.resolved_id in fixture_ids
            for mention in mentions
            if mention.resolved_id is not None
        )
        corpus = "\n".join(chunk.text for chunk in chunks).casefold()
        expected_hits = {
            model.id
            for model in fixtures
            if model.kind
            in (MemoryKind.PERSON, MemoryKind.ORGANIZATION, MemoryKind.LOCATION, MemoryKind.ASSET)
            and any(len(n) >= 3 and n.casefold() in corpus for n in (model.title,))
        }
        found = {m.resolved_id for m in mentions if m.resolved_id is not None}
        recall_ok = expected_hits <= found
        passed = no_inventions and recall_ok
        return EvalScore(
            case_id=case.case_id,
            stage=self.stage,
            score=1.0 if passed else (0.5 if no_inventions else 0.0),
            passed=passed,
            detail=(
                f"resolved {len(found)}/{len(expected_hits)} expected,"
                f" inventions={not no_inventions}"
            ),
        )


class ConflictDetectionEvaluator:
    """Ground-truth candidates vs fixture state: detected classes must match the
    expected conflicts exactly, and coexistence cases must NOT conflict."""

    def __init__(self, kinds: KindRegistry) -> None:
        self._kinds = kinds

    @property
    def stage(self) -> str:
        return "conflict_detection"

    def evaluate(self, case: EvalCase) -> EvalScore:
        fixtures = _existing_fixtures(case)
        detector = RuleConflictDetector(FixtureMemoryQuery(fixtures))
        candidates = _expected_candidates(case, self._kinds)
        reports = detector.detect(candidates)
        detected = sorted(report.conflict_class.value for report in reports)
        raw = case.expected.get("conflicts")
        expected = sorted(
            str(entry.get("conflict_class"))
            for entry in (raw if isinstance(raw, list) else [])
            if isinstance(entry, dict)
        )
        passed = detected == expected
        return EvalScore(
            case_id=case.case_id,
            stage=self.stage,
            score=1.0 if passed else 0.0,
            passed=passed,
            detail=f"detected={detected} expected={expected}",
        )


# ---------------------------------------------------------------------------
# LLM-backed evaluators (run when a provider is configured)
# ---------------------------------------------------------------------------


class EvidenceExtractionEvaluator:
    """Recall floor (evidence_min_count) + precision (must_not_extract avoided)."""

    def __init__(self, provider: LLMProvider, prompts: PromptRegistry) -> None:
        self._provider = provider
        self._prompts = prompts

    @property
    def stage(self) -> str:
        return "evidence_extraction"

    def evaluate(self, case: EvalCase) -> EvalScore:
        chunks = TurnChunker().chunk(case.transcript)
        extractor = LLMEvidenceExtractor(self._provider, self._prompts, PipelineTrace())
        evidence = extractor.extract(chunks)
        quotes = " || ".join(entry.quote.casefold() for entry in evidence)
        raw_min = case.expected.get("evidence_min_count")
        minimum = raw_min if isinstance(raw_min, int) else 1
        recall_ok = len(evidence) >= minimum
        raw_banned = case.expected.get("must_not_extract")
        banned = [str(b) for b in raw_banned] if isinstance(raw_banned, list) else []
        avoided = [b for b in banned if b.casefold() not in quotes]
        precision = len(avoided) / len(banned) if banned else 1.0
        score = (0.5 if recall_ok else 0.0) + 0.5 * precision
        return EvalScore(
            case_id=case.case_id,
            stage=self.stage,
            score=score,
            passed=score >= 1.0,
            detail=(
                f"{len(evidence)} quote(s) (min {minimum}),"
                f" avoided {len(avoided)}/{len(banned)} banned"
            ),
        )


class CandidateGenerationEvaluator:
    """F1 of generated candidates against expected (kind + attribute subset)."""

    def __init__(self, provider: LLMProvider, prompts: PromptRegistry, kinds: KindRegistry) -> None:
        self._provider = provider
        self._prompts = prompts
        self._kinds = kinds

    @property
    def stage(self) -> str:
        return "candidate_generation"

    def evaluate(self, case: EvalCase) -> EvalScore:
        trace = PipelineTrace()
        chunks = TurnChunker().chunk(case.transcript)
        extractor = LLMEvidenceExtractor(self._provider, self._prompts, trace)
        evidence = extractor.extract(chunks)
        fixtures = _existing_fixtures(case)
        resolver = HeuristicEntityResolver(FixtureMemoryQuery(fixtures))
        mentions = resolver.resolve(chunks, evidence)
        generator = LLMCandidateGenerator(self._provider, self._prompts, self._kinds, trace)
        generated = generator.generate(chunks, evidence, mentions)

        expected = _expected_candidates(case, self._kinds)
        matched = 0
        remaining = list(generated)
        for want in expected:
            hit = next((g for g in remaining if _matches(want, g)), None)
            if hit is not None:
                matched += 1
                remaining.remove(hit)
        precision = matched / len(generated) if generated else 0.0
        recall = matched / len(expected) if expected else 1.0
        f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
        return EvalScore(
            case_id=case.case_id,
            stage=self.stage,
            score=f1,
            passed=f1 >= 0.99,
            detail=f"matched {matched}/{len(expected)} expected, {len(generated)} generated",
        )


def _matches(expected: MemoryCandidate, generated: MemoryCandidate) -> bool:
    if expected.kind is not generated.kind:
        return False
    for key, want in expected.attributes.items():
        if want is None:
            continue
        have = generated.attributes.get(key)
        if isinstance(want, str) and isinstance(have, str):
            if want.casefold().strip() != have.casefold().strip():
                return False
        elif isinstance(want, list):
            have_set = {str(v).casefold() for v in have} if isinstance(have, list) else set()
            if not {str(v).casefold() for v in want} <= have_set:
                return False
        elif want != have:
            return False
    return True


# ---------------------------------------------------------------------------
# The suite
# ---------------------------------------------------------------------------


def deterministic_evaluators(kinds: KindRegistry) -> tuple[StageEvaluator, ...]:
    """The evaluators CI runs on every change (no provider required)."""
    return (
        ChunkingEvaluator(),
        EntityResolutionEvaluator(),
        ConflictDetectionEvaluator(kinds),
    )


def llm_evaluators(
    provider: LLMProvider, prompts: PromptRegistry, kinds: KindRegistry
) -> tuple[StageEvaluator, ...]:
    """The evaluators that need a configured provider (baseline records which)."""
    return (
        EvidenceExtractionEvaluator(provider, prompts),
        CandidateGenerationEvaluator(provider, prompts, kinds),
    )


def run_suite(
    cases: Sequence[EvalCase], evaluators: Sequence[StageEvaluator]
) -> tuple[dict[str, float], tuple[EvalScore, ...]]:
    """Run every evaluator over the cases that declare its stage; returns
    per-stage mean scores plus every individual score."""
    scores: list[EvalScore] = []
    for evaluator in evaluators:
        for case in cases:
            if evaluator.stage in case.stages or evaluator.stage == "chunking":
                scores.append(evaluator.evaluate(case))
    means = {
        stage: statistics.mean(s.score for s in scores if s.stage == stage)
        for stage in {s.stage for s in scores}
    }
    return means, tuple(scores)
