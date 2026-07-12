"""The ingestion orchestrator: wires the seven stage ports into one run.

Stateless stages, orchestrator-owned run state: partial re-runs (re-score without
re-extract) are natural. Terminal action is ``ProposalCommandService.open_proposal``
— stages 8 (human approval) and 9 (commit) are the existing review flow (ADR-0011).
Stub until roadmap phase 8.
"""

from engram_core.application.commands.proposal_commands import ProposalCommandService
from engram_intelligence.pipeline.stages import (
    CandidateGenerator,
    Chunker,
    ConflictDetector,
    EntityResolver,
    EvidenceExtractor,
    ImportanceScorer,
    ProposalAssembler,
)
from engram_intelligence.pipeline.types import IngestionOutcome, Transcript


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
    ) -> None:
        self._chunker = chunker
        self._extractor = extractor
        self._resolver = resolver
        self._generator = generator
        self._conflict_detector = conflict_detector
        self._scorer = scorer
        self._assembler = assembler
        self._proposals = proposals

    def ingest(self, transcript: Transcript) -> IngestionOutcome:
        """Run all stages and open one Proposal (or none, when nothing qualifies —
        an empty result is a good result).

        Raises:
            ValidationError: empty transcript.
        """
        raise NotImplementedError
