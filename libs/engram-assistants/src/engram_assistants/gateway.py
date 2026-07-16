"""The AssistantGateway: everything every assistant may do, defined once (ADR-0020).

Five operations, each behind a capability check. The gateway holds no reference to
any event-appending surface except two: ``record_access`` (the recall audit signal)
and the intelligence pipeline's proposal door. Approve/reject/merge/undo do not
exist here — consent is structural, not policed.
"""

import json
from collections.abc import Sequence
from dataclasses import dataclass

from engram_intelligence.pipeline.orchestrator import IngestionPipeline
from engram_intelligence.pipeline.types import IngestionOutcome, Transcript, Turn

from engram_assistants.contract import (
    AdapterDescriptor,
    AssistantContext,
    Capability,
    CapabilityError,
)
from engram_core.application.commands.memory_commands import MemoryCommandService
from engram_core.application.dto import MemoryReadModel
from engram_core.application.queries.memory_queries import MemoryQueryService
from engram_core.application.queries.proposal_queries import ProposalQueryService
from engram_core.application.queries.search_queries import SearchQueryService
from engram_core.application.queries.timeline_queries import TimelineQueryService
from engram_core.application.recall import recallable
from engram_core.domain.errors import NotFoundError
from engram_core.domain.values import MemoryId, ProposalId
from engram_events import Provenance

_MAX_SEARCH_LIMIT = 20
_HIDDEN = "no such memory: {0}"  # hidden must be indistinguishable from absent


@dataclass(frozen=True, slots=True)
class RecalledMemory:
    """What an assistant sees of a memory — the recallable surface, nothing more."""

    id: str
    kind: str
    slug: str
    title: str
    content: str
    attributes: dict[str, object]
    tags: tuple[str, ...]
    effective_confidence: float
    stale: bool

    @classmethod
    def from_model(cls, model: MemoryReadModel) -> "RecalledMemory":
        return cls(
            id=str(model.id),
            kind=model.kind.value,
            slug=model.slug,
            title=model.title,
            content=model.content,
            attributes=dict(model.attributes),
            tags=model.tags,
            effective_confidence=round(model.effective_confidence, 4),
            stale=model.stale,
        )

    def as_dict(self) -> dict[str, object]:
        return {
            "id": self.id,
            "kind": self.kind,
            "slug": self.slug,
            "title": self.title,
            "content": self.content,
            "attributes": self.attributes,
            "tags": list(self.tags),
            "effective_confidence": self.effective_confidence,
            "stale": self.stale,
        }


class AssistantGateway:
    """One gateway, many wire formats. Stateless per interaction."""

    SUPPORTED: frozenset[Capability] = frozenset(
        {
            Capability.RETRIEVAL,
            Capability.PROPOSAL_SUBMISSION,
            Capability.TIMELINE,
            Capability.TOOL_CALLING,
            Capability.STREAMING,
        }
    )

    def __init__(
        self,
        search: SearchQueryService,
        queries: MemoryQueryService,
        timeline: TimelineQueryService,
        commands: MemoryCommandService,
        pipeline: IngestionPipeline,
        proposals: ProposalQueryService,
    ) -> None:
        self._search = search
        self._queries = queries
        self._timeline = timeline
        self._commands = commands
        self._pipeline = pipeline
        self._proposals = proposals

    # -- negotiation ---------------------------------------------------------------

    def negotiate(self, descriptor: AdapterDescriptor) -> frozenset[Capability]:
        """Granted = declared ∩ supported. What is not granted does not run."""
        return descriptor.capabilities & self.SUPPORTED

    def _require(self, capability: Capability, descriptor: AdapterDescriptor) -> None:
        if capability not in self.negotiate(descriptor):
            raise CapabilityError(
                f"{descriptor.qualified_name} was not granted the"
                f" {capability.value!r} capability; this operation is unavailable"
            )

    # -- retrieval -------------------------------------------------------------------

    def recall_search(
        self,
        query: str,
        *,
        descriptor: AdapterDescriptor,
        context: AssistantContext,
        limit: int = 5,
    ) -> tuple[RecalledMemory, ...]:
        """Query-language search over recallable memories. Every returned hit
        records a ``MemoryAccessed`` — the audit trail and the retention signal
        are the same event (ADR-0009).

        Raises:
            CapabilityError: retrieval not granted.
            ValidationError: the query does not parse.
        """
        self._require(Capability.RETRIEVAL, descriptor)
        limit = max(1, min(limit, _MAX_SEARCH_LIMIT))
        page = self._search.query(query, limit=_MAX_SEARCH_LIMIT * 2)
        visible = [hit.memory for hit in page.items if recallable(hit.memory, descriptor.name)][
            :limit
        ]
        provenance = self._provenance(descriptor, context)
        for model in visible:
            self._commands.record_access(model.id, "assistant-search", provenance)
        return tuple(RecalledMemory.from_model(model) for model in visible)

    def recall_memory(
        self,
        memory_id: MemoryId,
        *,
        descriptor: AdapterDescriptor,
        context: AssistantContext,
    ) -> RecalledMemory:
        """One memory by id, visibility-checked. A memory this assistant may not
        see raises the same NotFoundError an unknown id raises.

        Raises:
            CapabilityError: retrieval not granted.
            NotFoundError: unknown id, or not recallable by this assistant.
        """
        self._require(Capability.RETRIEVAL, descriptor)
        model = self._queries.get_memory(memory_id)
        if not recallable(model, descriptor.name):
            raise NotFoundError(_HIDDEN.format(memory_id))
        self._commands.record_access(
            model.id, "assistant-recall", self._provenance(descriptor, context)
        )
        return RecalledMemory.from_model(model)

    # -- submission ------------------------------------------------------------------

    def remember(
        self,
        turns: Sequence[Turn],
        *,
        descriptor: AdapterDescriptor,
        context: AssistantContext,
    ) -> IngestionOutcome:
        """Submit conversation turns as candidate knowledge. The intelligence
        pipeline extracts, validates, scores — and opens ONE proposal. Nothing
        becomes memory until a human approves and merges it.

        Raises:
            CapabilityError: proposal submission not granted.
            ValidationError: empty transcript.
        """
        self._require(Capability.PROPOSAL_SUBMISSION, descriptor)
        transcript = Transcript(
            source=self._provenance(descriptor, context),
            turns=tuple(turns),
            transcript_id=context.session_id,
        )
        return self._pipeline.ingest(transcript)

    def proposal_status(
        self,
        proposal_id: ProposalId,
        *,
        descriptor: AdapterDescriptor,
    ) -> dict[str, object]:
        """Review status of a proposal — how an assistant learns whether the
        human accepted its submission.

        Raises:
            CapabilityError: proposal submission not granted.
            NotFoundError: unknown proposal.
        """
        self._require(Capability.PROPOSAL_SUBMISSION, descriptor)
        detail = self._proposals.get_proposal(proposal_id)
        return {
            "proposal_id": str(detail.id),
            "title": detail.title,
            "status": detail.status,
            "drafts": len(detail.drafts),
            "review_note": detail.review_note,
        }

    # -- explainability ----------------------------------------------------------------

    def memory_timeline(
        self,
        memory_id: MemoryId,
        *,
        descriptor: AdapterDescriptor,
    ) -> tuple[dict[str, object], ...]:
        """A recallable memory's event history — "why does engram believe this?".

        Raises:
            CapabilityError: timeline not granted.
            NotFoundError: unknown id, or not recallable by this assistant.
        """
        self._require(Capability.TIMELINE, descriptor)
        model = self._queries.get_memory(memory_id)
        if not recallable(model, descriptor.name):
            raise NotFoundError(_HIDDEN.format(memory_id))
        return tuple(
            {
                "seq": entry.stream_seq,
                "event_type": entry.event_type,
                "occurred_at": entry.occurred_at.isoformat(),
                "actor": entry.actor,
            }
            for entry in self._timeline.memory_timeline(memory_id)
        )

    # -- provenance --------------------------------------------------------------------

    @staticmethod
    def _provenance(descriptor: AdapterDescriptor, context: AssistantContext) -> Provenance:
        """Integration metadata (ADR-0020 §4): explanatory only, folded by nothing."""
        return Provenance(
            actor=descriptor.name,
            session_id=context.session_id,
            detail=json.dumps(
                {
                    "integration": {
                        "adapter": descriptor.name,
                        "adapter_version": descriptor.version,
                        "provider": descriptor.provider,
                        "model": context.model,
                        "capabilities": sorted(c.value for c in descriptor.capabilities),
                    }
                },
                sort_keys=True,
            ),
        )
