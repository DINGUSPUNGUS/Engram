"""The PluginGateway: everything every plugin may do, enforced in one place
(ADR-0024). Consumer capabilities only — provider-tier capabilities
(``intelligence_provider``, ``export_provider``, ``assistant_adapter``) have no
operation here at all; they are wired in at a composition root exactly like
``OllamaProvider`` already is (ADR-0024 §2).

The gateway holds no reference to any event-appending surface except two:
``record_access`` (the read audit signal, same as the assistant gateway) and
``ProposalCommandService.open_proposal`` — the same door M3's importer and
M4's reconciler already use. There is no ``approve``, ``reject``, ``merge``, or
``undo`` method here, at all, on purpose.
"""

from collections.abc import Sequence
from dataclasses import dataclass

from engram_core.application.commands.drafts import DraftIntent, to_dict
from engram_core.application.commands.memory_commands import MemoryCommandService
from engram_core.application.commands.proposal_commands import ProposalCommandService
from engram_core.application.dto import EvidenceView, MemoryReadModel, TimelineEntry
from engram_core.application.queries.memory_queries import MemoryQueryService
from engram_core.application.queries.search_queries import SearchQueryService
from engram_core.application.queries.timeline_queries import TimelineQueryService
from engram_core.application.recall import recallable
from engram_core.domain.errors import NotFoundError
from engram_core.domain.values import MemoryId
from engram_plugins.contract import Capability, CapabilityError, PluginContext, PluginDescriptor
from engram_plugins.provenance import actor_for, build_provenance

_MAX_QUERY_LIMIT = 50
_HIDDEN = "no such memory: {0}"  # hidden must be indistinguishable from absent, same as ADR-0020


@dataclass(frozen=True, slots=True)
class PluginMemoryView:
    """What a plugin sees of a memory — the recallable surface, nothing more.
    Deliberately the same shape a plugin would get from a real read; there is
    no richer "trusted" view a plugin can reach."""

    id: str
    kind: str
    slug: str
    title: str
    content: str
    attributes: dict[str, object]
    tags: tuple[str, ...]
    evidence: tuple[EvidenceView, ...]
    effective_confidence: float
    version: int  # the aggregate version this view was read at (for base_version)

    @classmethod
    def from_model(cls, model: MemoryReadModel) -> "PluginMemoryView":
        return cls(
            id=str(model.id),
            kind=model.kind.value,
            slug=model.slug,
            title=model.title,
            content=model.content,
            attributes=dict(model.attributes),
            tags=model.tags,
            evidence=model.evidence,
            effective_confidence=round(model.effective_confidence, 4),
            version=model.version,
        )


class PluginGateway:
    """One gateway for every consumer plugin. Stateless per interaction."""

    #: Grantable through this gateway. Provider-tier capabilities are never
    #: in here — see module docstring and ADR-0024 §2.
    SUPPORTED: frozenset[Capability] = frozenset(
        {
            Capability.MEMORY_READ,
            Capability.QUERY,
            Capability.TIMELINE_READ,
            Capability.EVIDENCE_READ,
            Capability.PROPOSAL_SUBMIT,
        }
    )

    def __init__(
        self,
        queries: MemoryQueryService,
        search: SearchQueryService,
        timeline: TimelineQueryService,
        commands: MemoryCommandService,
        proposals: ProposalCommandService,
    ) -> None:
        self._queries = queries
        self._search = search
        self._timeline = timeline
        self._commands = commands
        self._proposals = proposals

    # -- negotiation ---------------------------------------------------------------

    def negotiate(self, descriptor: PluginDescriptor) -> frozenset[Capability]:
        """Granted = declared ∩ supported. What is not granted does not run."""
        return descriptor.capabilities & self.SUPPORTED

    def _require(self, capability: Capability, descriptor: PluginDescriptor) -> None:
        if capability not in self.negotiate(descriptor):
            raise CapabilityError(
                f"{descriptor.qualified_name} was not granted the {capability.value!r}"
                " capability; this operation is unavailable"
            )

    # -- read: memory ----------------------------------------------------------------

    def get_memory(
        self, memory_id: MemoryId, *, descriptor: PluginDescriptor, context: PluginContext
    ) -> PluginMemoryView:
        """One memory by id, visibility-checked exactly as for an assistant
        (plugins are at least as untrusted, never more).

        Raises:
            CapabilityError: memory_read not granted.
            NotFoundError: unknown id, or not recallable by this plugin.
        """
        self._require(Capability.MEMORY_READ, descriptor)
        model = self._queries.get_memory(memory_id)
        if not recallable(model, actor_for(descriptor)):
            raise NotFoundError(_HIDDEN.format(memory_id))
        self._record_access(model.id, descriptor, context, Capability.MEMORY_READ)
        return PluginMemoryView.from_model(model)

    def query(
        self,
        text: str,
        *,
        descriptor: PluginDescriptor,
        context: PluginContext,
        limit: int = 20,
    ) -> tuple[PluginMemoryView, ...]:
        """Query-language search over recallable memories (ADR-0016).

        Raises:
            CapabilityError: query not granted.
            ValidationError: the query does not parse.
        """
        self._require(Capability.QUERY, descriptor)
        limit = max(1, min(limit, _MAX_QUERY_LIMIT))
        page = self._search.query(text, limit=_MAX_QUERY_LIMIT * 2)
        actor = actor_for(descriptor)
        visible = [hit.memory for hit in page.items if recallable(hit.memory, actor)][:limit]
        for model in visible:
            self._record_access(model.id, descriptor, context, Capability.QUERY)
        return tuple(PluginMemoryView.from_model(model) for model in visible)

    def timeline_for(
        self, memory_id: MemoryId, *, descriptor: PluginDescriptor, context: PluginContext
    ) -> Sequence[TimelineEntry]:
        """A recallable memory's event history — explainability, not a write path.

        Raises:
            CapabilityError: timeline_read not granted.
            NotFoundError: unknown id, or not recallable by this plugin.
        """
        self._require(Capability.TIMELINE_READ, descriptor)
        model = self._queries.get_memory(memory_id)
        if not recallable(model, actor_for(descriptor)):
            raise NotFoundError(_HIDDEN.format(memory_id))
        return self._timeline.memory_timeline(memory_id)

    def evidence_for(
        self, memory_id: MemoryId, *, descriptor: PluginDescriptor, context: PluginContext
    ) -> tuple[EvidenceView, ...]:
        """A recallable memory's current evidence list — so a plugin can avoid
        proposing evidence that already exists.

        Raises:
            CapabilityError: evidence_read not granted.
            NotFoundError: unknown id, or not recallable by this plugin.
        """
        self._require(Capability.EVIDENCE_READ, descriptor)
        model = self._queries.get_memory(memory_id)
        if not recallable(model, actor_for(descriptor)):
            raise NotFoundError(_HIDDEN.format(memory_id))
        self._record_access(model.id, descriptor, context, Capability.EVIDENCE_READ)
        return model.evidence

    # -- proposal: the only write door ------------------------------------------------

    def submit_proposal(
        self,
        title: str,
        description: str,
        drafts: Sequence[DraftIntent],
        *,
        descriptor: PluginDescriptor,
        context: PluginContext,
    ) -> str:
        """Open ONE proposal carrying draft intents. This is the *entire*
        write surface a plugin has: it appends an event only to the Proposal
        aggregate's own stream (``ProposalOpened``), never to a Memory stream
        (ADR-0024 §3). Nothing becomes memory until a human approves and
        merges it — the gateway has no method that could do either.

        Raises:
            CapabilityError: proposal_submit not granted.
            ValidationError: empty title, no drafts, or malformed drafts.
        """
        self._require(Capability.PROPOSAL_SUBMIT, descriptor)
        provenance = build_provenance(descriptor, context, Capability.PROPOSAL_SUBMIT)
        proposal_id = self._proposals.open_proposal(
            title, description, [to_dict(d) for d in drafts], provenance
        )
        return str(proposal_id)

    # -- plumbing ----------------------------------------------------------------------

    def _record_access(
        self,
        memory_id: MemoryId,
        descriptor: PluginDescriptor,
        context: PluginContext,
        cap: Capability,
    ) -> None:
        provenance = build_provenance(descriptor, context, cap)
        self._commands.record_access(memory_id, f"plugin-{cap.value}", provenance)
