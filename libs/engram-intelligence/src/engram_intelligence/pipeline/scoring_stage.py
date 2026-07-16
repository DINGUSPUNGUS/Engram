"""Stage 6: PolicyImportanceScorer — the scoring policy applied, never invented.

Scoring is separated from extraction by design: extraction discovers, scoring
evaluates, assembly packages. Every number comes from the one tunable module
(``engram_core.domain.scoring``, ADR-0009/0019); the rationale string spells the
arithmetic out so a reviewer never has to reverse-engineer a score.
"""

import dataclasses
from collections.abc import Sequence

from engram_core.domain import scoring
from engram_intelligence.pipeline.types import (
    ConflictClass,
    ConflictReport,
    MemoryCandidate,
    ScoredCandidate,
)


class PolicyImportanceScorer:
    """Attaches importance and confidence priors from policy constants."""

    def score(
        self,
        candidates: Sequence[MemoryCandidate],
        conflicts: Sequence[ConflictReport],
    ) -> Sequence[ScoredCandidate]:
        contradicted = {
            report.candidate_index
            for report in conflicts
            if report.conflict_class is ConflictClass.CONTRADICTION
        }
        scored: list[ScoredCandidate] = []
        for index, candidate in enumerate(candidates):
            importance = scoring.candidate_importance(
                candidate.kind,
                evidence_count=len(candidate.evidence),
                link_count=len(candidate.links),
                contradicts_existing=index in contradicted,
            )
            prior = (
                candidate.confidence_prior
                if candidate.confidence_prior is not None
                else scoring.CONFIDENCE_PRIOR_ASSISTANT_INFERRED
            )
            rationale = (
                f"kind base {scoring.IMPORTANCE_KIND_BASE[candidate.kind]:.2f}"
                f" + evidence x{min(len(candidate.evidence), 3)}"
                f" + links x{min(len(candidate.links), 4)}"
                + (" + contradiction boost" if index in contradicted else "")
                + f"; confidence prior {prior:.2f} (assistant-inferred)"
            )
            scored.append(
                ScoredCandidate(
                    candidate=dataclasses.replace(candidate, confidence_prior=prior),
                    importance=importance,
                    rationale=rationale,
                )
            )
        return scored
