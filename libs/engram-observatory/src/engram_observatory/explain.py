"""The question-answering surface: reconstructed reasoning chains on demand.

Stubs — each method is implemented alongside the subsystem it explains (scoring,
conflict detection, pipeline, evals). The contract exists now so those subsystems
are built emitting traces, not retrofitted with them.
"""

from uuid import UUID

from engram_core.domain.values import MemoryId, ProposalId
from engram_observatory.recorder import TraceRecorder
from engram_observatory.trace import DecisionTrace


class ExplanationService:
    """Answers "why?" by assembling traces, event history, and scoring inputs."""

    def __init__(self, recorder: TraceRecorder) -> None:
        self._recorder = recorder

    def why_created(self, memory_id: MemoryId) -> DecisionTrace:
        """Which conversation, evidence, prompts, and approvals produced this memory."""
        raise NotImplementedError

    def why_not_created(self, proposal_id: ProposalId, candidate_index: int) -> DecisionTrace:
        """Which stage, rule, or reviewer rejected a candidate — and on what grounds."""
        raise NotImplementedError

    def why_confidence(self, memory_id: MemoryId) -> DecisionTrace:
        """The full arithmetic: prior, confirmations, contradictions, time decay."""
        raise NotImplementedError

    def why_duplicate(self, memory_id: MemoryId, other_id: MemoryId) -> DecisionTrace:
        """Which signals (aliases, channels, names) matched, with their weights."""
        raise NotImplementedError

    def why_evaluation_failed(self, case_id: str, run_id: UUID) -> DecisionTrace:
        """Expected vs. actual per stage for one golden/synthetic case run."""
        raise NotImplementedError
