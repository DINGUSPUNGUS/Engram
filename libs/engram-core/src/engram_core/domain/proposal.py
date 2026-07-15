"""The Proposal aggregate: PR-style review for memory changes.

A proposal carries a set of *proposed* events targeting memory streams. While the
proposal is open, those events exist only inside the proposal's own stream. On
merge, the application layer appends them to their target streams (with fresh
sequence numbers, re-validated against current state — which is where conflict
detection lives).

M3 implemented open/fold (the importer's vehicle: nothing imported bypasses
proposals). Approve/reject/merge land with M4. If this abstraction proves heavier
than needed, ADR-0002 records the fallback (plain draft events).
"""

import dataclasses
from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum
from uuid import UUID

from engram_core.domain import events as ev
from engram_core.domain.errors import ConflictError, ValidationError
from engram_core.domain.values import ProposalId
from engram_events import EventEnvelope


class ProposalStatus(StrEnum):
    DRAFT = "draft"
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    MERGED = "merged"
    UNDONE = "undone"


@dataclass
class Proposal:
    """A reviewable batch of memory changes, folded from its event stream."""

    id: ProposalId
    title: str
    description: str
    status: ProposalStatus
    proposed_events: tuple[dict[str, object], ...] = ()
    review_note: str | None = None
    merged_event_ids: tuple[UUID, ...] = ()
    version: int = 0

    @classmethod
    def fold(cls, envelopes: Sequence[EventEnvelope]) -> "Proposal":
        """Rebuild current state from the proposal's stream.

        Raises:
            ValidationError: empty stream or wrong first event.
        """
        if not envelopes:
            raise ValidationError("cannot fold an empty proposal stream")
        first = envelopes[0].payload
        if not isinstance(first, ev.ProposalOpened):
            raise ValidationError(
                f"proposal stream must start with ProposalOpened, got {envelopes[0].event_type}"
            )
        proposal = cls(
            id=ProposalId(first.proposal_id),
            title=first.title,
            description=first.description,
            status=ProposalStatus.PENDING,
            proposed_events=tuple(first.proposed_events),
            version=envelopes[0].stream_seq,
        )
        for envelope in envelopes[1:]:
            proposal = proposal.evolve(envelope)
        return proposal

    def evolve(self, envelope: EventEnvelope) -> "Proposal":
        """Return the state after one more event. Pure."""
        payload = envelope.payload
        changes: dict[str, object]
        match payload:
            case ev.ProposalApproved():
                changes = {"status": ProposalStatus.APPROVED, "review_note": payload.note}
            case ev.ProposalRejected():
                changes = {"status": ProposalStatus.REJECTED, "review_note": payload.note}
            case ev.ProposalMerged():
                changes = {
                    "status": ProposalStatus.MERGED,
                    "merged_event_ids": tuple(payload.appended_event_ids),
                }
            case ev.ProposalUndone():
                changes = {"status": ProposalStatus.UNDONE}
            case _:
                raise ValidationError(
                    f"event type not foldable on proposals: {envelope.event_type}"
                )
        return dataclasses.replace(self, version=envelope.stream_seq, **changes)  # type: ignore[arg-type]

    @staticmethod
    def decide_open(
        proposal_id: ProposalId,
        title: str,
        description: str,
        proposed_events: Sequence[dict[str, object]],
    ) -> Sequence[object]:
        """Produce ``ProposalOpened``.

        Raises:
            ValidationError: empty title or no proposed events (an empty proposal
                is unreviewable noise).
        """
        if not title.strip():
            raise ValidationError("proposal title must not be empty")
        if not proposed_events:
            raise ValidationError("a proposal must carry at least one proposed event")
        return (
            ev.ProposalOpened(
                proposal_id=proposal_id,
                title=title.strip(),
                description=description,
                proposed_events=tuple(dict(event) for event in proposed_events),
            ),
        )

    def decide_approve(self, note: str | None = None) -> Sequence[object]:
        """Produce ``ProposalApproved``.

        Raises:
            ConflictError: unless status is ``pending`` or ``draft``.
        """
        self._require_reviewable("approve")
        return (ev.ProposalApproved(note=note),)

    def decide_reject(self, note: str | None = None) -> Sequence[object]:
        """Produce ``ProposalRejected``.

        Raises:
            ConflictError: unless status is ``pending`` or ``draft``.
        """
        self._require_reviewable("reject")
        return (ev.ProposalRejected(note=note),)

    def decide_merge(self, appended_event_ids: Sequence[UUID]) -> Sequence[object]:
        """Produce ``ProposalMerged``. The application service supplies the ids of
        the aggregate-decided events it is appending in the same atomic batch.

        Raises:
            ConflictError: unless status is ``approved``.
        """
        if self.status is not ProposalStatus.APPROVED:
            raise ConflictError(
                f"proposal {self.id} is {self.status.value}; only approved proposals merge"
            )
        return (ev.ProposalMerged(appended_event_ids=tuple(appended_event_ids)),)

    def decide_undo(
        self, compensating_event_ids: Sequence[UUID], note: str | None = None
    ) -> Sequence[object]:
        """Produce ``ProposalUndone`` (ADR-0018: compensation, never erasure).

        Raises:
            ConflictError: unless status is ``merged``.
        """
        if self.status is not ProposalStatus.MERGED:
            raise ConflictError(
                f"proposal {self.id} is {self.status.value}; only merged proposals undo"
            )
        return (ev.ProposalUndone(note=note, compensating_event_ids=tuple(compensating_event_ids)),)

    def _require_reviewable(self, action: str) -> None:
        if self.status not in (ProposalStatus.DRAFT, ProposalStatus.PENDING):
            raise ConflictError(f"cannot {action} proposal {self.id}: already {self.status.value}")
