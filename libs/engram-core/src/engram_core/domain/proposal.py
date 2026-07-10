"""The Proposal aggregate: PR-style review for memory changes.

A proposal carries a set of *proposed* events targeting memory streams. While the
proposal is open, those events exist only inside the proposal's own stream. On
merge, the application layer appends them to their target streams (with fresh
sequence numbers, re-validated against current state — which is where conflict
detection lives).

Stub bodies; signatures are the contract. If this abstraction proves heavier than
needed, ADR-0002 records the fallback (plain draft events).
"""

from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum

from engram_core.domain.values import ProposalId
from engram_events import EventEnvelope


class ProposalStatus(StrEnum):
    DRAFT = "draft"
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    MERGED = "merged"


@dataclass
class Proposal:
    """A reviewable batch of memory changes, folded from its event stream."""

    id: ProposalId
    title: str
    description: str
    status: ProposalStatus
    proposed_events: tuple[dict[str, object], ...] = ()
    review_note: str | None = None
    version: int = 0

    @classmethod
    def fold(cls, envelopes: Sequence[EventEnvelope]) -> "Proposal":
        """Rebuild current state from the proposal's stream."""
        raise NotImplementedError

    def evolve(self, envelope: EventEnvelope) -> "Proposal":
        """Return the state after one more event."""
        raise NotImplementedError

    @staticmethod
    def decide_open(
        proposal_id: ProposalId,
        title: str,
        description: str,
        proposed_events: Sequence[dict[str, object]],
    ) -> Sequence[object]:
        """Produce ``ProposalOpened``."""
        raise NotImplementedError

    def decide_approve(self, note: str | None = None) -> Sequence[object]:
        """Produce ``ProposalApproved``.

        Raises:
            ConflictError: unless status is ``pending`` or ``draft``.
        """
        raise NotImplementedError

    def decide_reject(self, note: str | None = None) -> Sequence[object]:
        """Produce ``ProposalRejected``."""
        raise NotImplementedError

    def decide_merge(self) -> Sequence[object]:
        """Produce ``ProposalMerged``.

        Raises:
            ConflictError: unless status is ``approved``.
        """
        raise NotImplementedError
