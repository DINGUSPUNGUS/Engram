"""Proposal command service: PR-style review over memory changes.

Merging is the interesting one: proposed events are re-validated against the
*current* state of their target streams — a target that moved since the proposal
was opened is a conflict, surfaced as ``StaleVersionError`` (never a silent
overwrite). Bodies are architecture-phase stubs.
"""

from collections.abc import Sequence

from engram_core.domain.ports import Clock, MemoryRepository, ProposalRepository
from engram_core.domain.values import ProposalId
from engram_events import EventBus, Provenance


class ProposalCommandService:
    """All write operations on proposals."""

    def __init__(
        self,
        proposals: ProposalRepository,
        memories: MemoryRepository,
        bus: EventBus,
        clock: Clock,
    ) -> None:
        self._proposals = proposals
        self._memories = memories
        self._bus = bus
        self._clock = clock

    def open_proposal(
        self,
        title: str,
        description: str,
        proposed_events: Sequence[dict[str, object]],
        provenance: Provenance,
    ) -> ProposalId:
        """Open a proposal carrying serialized draft envelopes."""
        raise NotImplementedError

    def approve_proposal(
        self, proposal_id: ProposalId, note: str | None, provenance: Provenance
    ) -> None:
        """Mark an open proposal approved."""
        raise NotImplementedError

    def reject_proposal(
        self, proposal_id: ProposalId, note: str | None, provenance: Provenance
    ) -> None:
        """Reject an open proposal."""
        raise NotImplementedError

    def merge_proposal(self, proposal_id: ProposalId, provenance: Provenance) -> None:
        """Execute an approved proposal: append its events to their target streams.

        Raises:
            ConflictError: proposal not approved.
            StaleVersionError: a target stream moved since the proposal was opened.
        """
        raise NotImplementedError
