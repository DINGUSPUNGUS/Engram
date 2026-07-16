"""The ingestion orchestrator: wires the seven stage ports into one run.

Stateless stages, orchestrator-owned run state: partial re-runs (re-score without
re-extract) are natural. Terminal action is ``ProposalCommandService.open_proposal``
— stages 8 (human approval) and 9 (commit) are the existing review flow (ADR-0011).

The pipeline's only authority is to produce proposals. It never appends memory
events, and it is side-effect free until a human merges: an ingest that finds
nothing durable writes nothing at all. The run's full explanation (provider,
model, prompts, scoring, notes) rides ``Provenance.detail`` on the proposal's
opening envelope (ADR-0019 §3).
"""

import json

from engram_core.application.commands.proposal_commands import ProposalCommandService
from engram_core.domain.errors import ValidationError
from engram_intelligence.pipeline.stages import (
    CandidateGenerator,
    Chunker,
    ConflictDetector,
    EntityResolver,
    EvidenceExtractor,
    ImportanceScorer,
    ProposalAssembler,
)
from engram_intelligence.pipeline.trace import PipelineTrace
from engram_intelligence.pipeline.types import IngestionOutcome, Transcript

_PIPELINE_VERSION = "ingestion/1"


class IngestionPipeline:
    """Conversation in, Proposal out. Never writes a memory stream directly."""

    def __init__(
        self,
        chunker: Chunker,
        extractor: EvidenceExtractor,
        resolver: EntityResolver,
        generator: CandidateGenerator,
        conflict_detector: ConflictDetector,
        scorer: ImportanceScorer,
        assembler: ProposalAssembler,
        proposals: ProposalCommandService,
        trace: PipelineTrace | None = None,
    ) -> None:
        self._chunker = chunker
        self._extractor = extractor
        self._resolver = resolver
        self._generator = generator
        self._conflict_detector = conflict_detector
        self._scorer = scorer
        self._assembler = assembler
        self._proposals = proposals
        self._trace = trace if trace is not None else PipelineTrace()

    def ingest(self, transcript: Transcript) -> IngestionOutcome:
        """Run all stages and open one Proposal (or none, when nothing qualifies —
        an empty result is a good result).

        Raises:
            ValidationError: empty transcript.
            StorageError: provider failure (nothing has been written).
        """
        if not any(turn.content.strip() for turn in transcript.turns):
            raise ValidationError("cannot ingest an empty transcript")
        self._trace.reset()

        chunks = self._chunker.chunk(transcript)
        evidence = self._extractor.extract(chunks)
        if not evidence:
            return self._empty(0, 0, "no durable evidence found")
        mentions = self._resolver.resolve(chunks, evidence)
        candidates = self._generator.generate(chunks, evidence, mentions)
        if not candidates:
            return self._empty(0, 0, "no valid candidates generated")
        conflicts = self._conflict_detector.detect(candidates)
        scored = self._scorer.score(candidates, conflicts)
        draft = self._assembler.assemble(transcript, scored, conflicts)
        if not draft.proposed_events:
            return self._empty(len(candidates), len(conflicts), "nothing new to propose")

        counts = {
            "turns": len(transcript.turns),
            "chunks": len(chunks),
            "evidence": len(evidence),
            "mentions": len(mentions),
            "candidates": len(candidates),
            "conflicts": len(conflicts),
            "intents": len(draft.proposed_events),
        }
        metadata = {
            "pipeline": _PIPELINE_VERSION,
            "source": {
                "actor": transcript.source.actor,
                "session_id": transcript.source.session_id,
                "transcript_id": transcript.transcript_id,
            },
            "prompts": sorted({call.prompt for call in self._trace.calls}),
            "counts": counts,
            **self._trace.as_metadata(),
        }
        provenance = type(transcript.source)(
            actor=transcript.source.actor,
            session_id=transcript.source.session_id,
            detail=json.dumps(metadata, sort_keys=True),
        )
        proposal_id = self._proposals.open_proposal(
            draft.title, draft.description, list(draft.proposed_events), provenance
        )
        return IngestionOutcome(
            proposal_id=proposal_id,
            candidate_count=len(candidates),
            conflict_count=len(conflicts),
            skipped_reasons=tuple(self._trace.notes),
        )

    def _empty(self, candidates: int, conflicts: int, reason: str) -> IngestionOutcome:
        return IngestionOutcome(
            proposal_id=None,
            candidate_count=candidates,
            conflict_count=conflicts,
            skipped_reasons=(*self._trace.notes, reason),
        )
