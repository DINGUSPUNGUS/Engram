"""Proposal read side: the review queue (projection) and full inspection (fold).

Inspection deliberately folds the proposal's own event stream rather than reading
projection rows — what a reviewer sees is the history, not a cache of it.
"""

from engram_core.application.dto import Page, ProposalDetail, ProposalListItem
from engram_core.domain.ports import ProposalQuery, ProposalRepository
from engram_core.domain.values import ProposalId


class ProposalQueryService:
    """Read-only access to proposals."""

    def __init__(self, repository: ProposalRepository, query: ProposalQuery) -> None:
        self._repository = repository
        self._query = query

    def list_proposals(
        self, *, status: str | None = None, limit: int = 50
    ) -> Page[ProposalListItem]:
        """The review queue, newest first."""
        return self._query.list_proposals(status=status, limit=limit)

    def get_proposal(self, proposal_id: ProposalId) -> ProposalDetail:
        """One proposal in full, folded from its stream (drafts included).

        Raises:
            NotFoundError: unknown proposal.
        """
        proposal = self._repository.load(proposal_id)
        return ProposalDetail(
            id=proposal.id,
            title=proposal.title,
            description=proposal.description,
            status=proposal.status.value,
            review_note=proposal.review_note,
            drafts=proposal.proposed_events,
            merged_event_ids=proposal.merged_event_ids,
            version=proposal.version,
        )
