"""Proposal command service: PR-style review over memory changes.

Merging is the interesting one: proposed events are re-validated against the
*current* state of their target streams — a target that moved since the proposal
was opened is a conflict, surfaced as ``StaleVersionError`` (never a silent
overwrite). M3 implemented ``open_proposal`` (the importer's front door);
approve/reject/merge land with M4.
"""

from collections.abc import Sequence

from engram_core.domain.ports import Clock, MemoryRepository, ProposalRepository
from engram_core.domain.proposal import Proposal
from engram_core.domain.values import ProposalId, new_proposal_id
from engram_events import EventBus, EventEnvelope, Provenance, new_uuid7


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
        """Open a proposal carrying serialized draft events.

        This is the only door automation and imports have into memory (ADR-0011):
        the drafts sit in the proposal's own stream until a human approves and
        merges them (M4).

        Raises:
            ValidationError: empty title or no drafts.
        """
        proposal_id = new_proposal_id()
        payloads = Proposal.decide_open(proposal_id, title, description, proposed_events)
        occurred_at = self._clock.now()
        envelopes = [
            EventEnvelope(
                event_id=new_uuid7(),
                stream_id=proposal_id,
                stream_seq=offset + 1,
                event_type=type(payload).__name__,
                schema_version=1,
                payload=payload,
                occurred_at=occurred_at,
                provenance=provenance,
            )
            for offset, payload in enumerate(payloads)
        ]
        appended = self._proposals.append(envelopes)
        self._bus.publish(appended)
        return proposal_id

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
