"""Pipeline composition + transcript parsing for ``engram ingest``.

This is composition-root code: the only place in the CLI that names provider
implementations (ADR-0012). Provider selection is configuration —
``ENGRAM_LLM_PROVIDER`` — with Ollama as the local-first default and ``fake``
(canned responses from a JSON file) for reproducible demos, tests, and CI.
"""

import re
from pathlib import Path

from engram_intelligence.pipeline.assembly import DraftProposalAssembler
from engram_intelligence.pipeline.chunking import TurnChunker
from engram_intelligence.pipeline.conflicts import RuleConflictDetector
from engram_intelligence.pipeline.extraction import LLMEvidenceExtractor
from engram_intelligence.pipeline.generation import LLMCandidateGenerator
from engram_intelligence.pipeline.orchestrator import IngestionPipeline
from engram_intelligence.pipeline.resolution import HeuristicEntityResolver
from engram_intelligence.pipeline.scoring_stage import PolicyImportanceScorer
from engram_intelligence.pipeline.trace import PipelineTrace, TracingProvider
from engram_intelligence.pipeline.types import Transcript, Turn, TurnRole
from engram_intelligence.prompts.registry import load_library
from engram_intelligence.provider import FakeProvider, LLMProvider
from engram_intelligence.providers.ollama import OllamaProvider

from engram_cli.config import CliSettings
from engram_cli.runtime import Runtime
from engram_core.domain.errors import ValidationError
from engram_core.domain.kinds import build_kind_registry
from engram_events import Provenance

_TURN_PATTERN = re.compile(r"^(USER|ASSISTANT):\s?(.*)$")


def build_provider(settings: CliSettings, trace: PipelineTrace) -> LLMProvider:
    """Resolve the configured provider (never called anywhere else).

    Raises:
        ValidationError: unknown provider name or missing fake-responses file.
    """
    match settings.llm_provider:
        case "ollama":
            provider = OllamaProvider(
                settings.llm_model,
                settings.llm_base_url,
                timeout_seconds=settings.llm_timeout_seconds,
                seed=settings.llm_seed,
            )
            trace.configure(
                provider="ollama",
                model=settings.llm_model,
                seed=settings.llm_seed,
                temperature=0.0,
            )
            return provider
        case "fake":
            if settings.llm_fake_responses is None:
                raise ValidationError(
                    "ENGRAM_LLM_PROVIDER=fake needs ENGRAM_LLM_FAKE_RESPONSES=<json file>"
                )
            trace.configure(provider="fake", responses_file=str(settings.llm_fake_responses))
            return FakeProvider.from_json_file(settings.llm_fake_responses)
        case other:
            raise ValidationError(f"unknown ENGRAM_LLM_PROVIDER {other!r}; supported: ollama, fake")


def build_pipeline(runtime: Runtime, settings: CliSettings) -> IngestionPipeline:
    """Wire the seven stages. Every LLM call goes through the tracing decorator
    so the resulting proposal carries its full explanation (ADR-0019 §3)."""
    trace = PipelineTrace()
    provider = TracingProvider(build_provider(settings, trace), trace)
    prompts = load_library()
    kinds = build_kind_registry()
    query = runtime.query_engine
    return IngestionPipeline(
        chunker=TurnChunker(),
        extractor=LLMEvidenceExtractor(provider, prompts, trace),
        resolver=HeuristicEntityResolver(query),
        generator=LLMCandidateGenerator(provider, prompts, kinds, trace),
        conflict_detector=RuleConflictDetector(query),
        scorer=PolicyImportanceScorer(),
        assembler=DraftProposalAssembler(query, kinds, trace),
        proposals=runtime.proposals,
        trace=trace,
    )


def parse_transcript_file(path: Path, source: Provenance) -> Transcript:
    """Parse a ``USER:`` / ``ASSISTANT:`` transcript file (unprefixed lines
    continue the current turn — the same format the golden cases use).

    Raises:
        ValidationError: unreadable file or no turns found.
    """
    try:
        text = path.read_text(encoding="utf-8-sig")
    except OSError as exc:
        raise ValidationError(f"cannot read transcript {path}: {exc}") from exc
    turns: list[tuple[TurnRole, list[str]]] = []
    for line in text.splitlines():
        match = _TURN_PATTERN.match(line)
        if match:
            turns.append((TurnRole(match.group(1).lower()), [match.group(2)]))
        elif line.strip() and turns:
            turns[-1][1].append(line.strip())
    if not turns:
        raise ValidationError(
            f"no turns found in {path} — lines must start with 'USER:' or 'ASSISTANT:'"
        )
    return Transcript(
        source=source,
        turns=tuple(Turn(role=role, content=" ".join(lines).strip()) for role, lines in turns),
        transcript_id=path.name,
    )
