"""Stage contracts (Protocols) for the ingestion pipeline (docs/intelligence.md §1).

Each stage is independently replaceable and independently evaluated against golden
cases (ADR-0014). LLM-backed implementations receive an ``LLMProvider`` and a
``PromptRegistry`` via their constructors; heuristic implementations need neither —
the contract cannot tell the difference, which is the point.
"""

from collections.abc import Sequence
from typing import Protocol

from engram_intelligence.pipeline.types import (
    Chunk,
    ConflictReport,
    EntityMention,
    ExtractedEvidence,
    MemoryCandidate,
    ProposalDraft,
    ScoredCandidate,
    Transcript,
)


class Chunker(Protocol):
    """Stage 1: split a transcript into semantically coherent chunks."""

    def chunk(self, transcript: Transcript) -> Sequence[Chunk]: ...


class EvidenceExtractor(Protocol):
    """Stage 2: pull verbatim quotes worth remembering. Precision over recall —
    what NOT to remember is the harder half of the job."""

    def extract(self, chunks: Sequence[Chunk]) -> Sequence[ExtractedEvidence]: ...


class EntityResolver(Protocol):
    """Stage 3: resolve mentions against existing person/org/location/asset
    memories via alias sets and search. Unresolved mentions stay unresolved —
    guessing an id corrupts the graph."""

    def resolve(
        self, chunks: Sequence[Chunk], evidence: Sequence[ExtractedEvidence]
    ) -> Sequence[EntityMention]: ...


class CandidateGenerator(Protocol):
    """Stage 4: draft typed MemoryCandidates. MUST validate attributes against the
    KindRegistry — an invalid candidate never leaves this stage."""

    def generate(
        self,
        chunks: Sequence[Chunk],
        evidence: Sequence[ExtractedEvidence],
        mentions: Sequence[EntityMention],
    ) -> Sequence[MemoryCandidate]: ...


class ConflictDetector(Protocol):
    """Stage 5: find duplicates and contradictions against current state
    (memory-model.md §8). Detection only — resolution belongs to review."""

    def detect(self, candidates: Sequence[MemoryCandidate]) -> Sequence[ConflictReport]: ...


class ImportanceScorer(Protocol):
    """Stage 6: attach importance/confidence priors (scoring.py constants).
    Heuristics first; models only when evaluations prove they beat heuristics."""

    def score(
        self,
        candidates: Sequence[MemoryCandidate],
        conflicts: Sequence[ConflictReport],
    ) -> Sequence[ScoredCandidate]: ...


class ProposalAssembler(Protocol):
    """Stage 7: bundle everything into ONE reviewable ProposalDraft — creates,
    edits, links, merges, and contradiction flags, with prompt versions stamped."""

    def assemble(
        self,
        transcript: Transcript,
        scored: Sequence[ScoredCandidate],
        conflicts: Sequence[ConflictReport],
    ) -> ProposalDraft: ...
