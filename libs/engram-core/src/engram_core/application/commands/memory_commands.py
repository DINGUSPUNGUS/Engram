"""Memory command service.

The choreography every command follows (ADR-0002):

1. load the aggregate (replay its stream) — or start fresh for ``create``,
2. call the aggregate's ``decide_*`` to validate and produce payloads,
3. wrap payloads in envelopes (event id, stream seq, provenance, clock),
4. append via the repository (optimistic concurrency on ``stream_seq``),
5. publish the appended envelopes on the bus so projections fan out.

M1 implemented the narrative core; M4 added the spine. ``undo_last_change``
compensates the single most recent event on one stream — the same inverse-event
table ``ProposalCommandService.undo_proposal`` uses (ADR-0018 §3), applied to one
stream instead of a proposal's whole merge batch.
"""

from collections.abc import Sequence
from uuid import UUID

from engram_core.application.commands.compensation import compensate, fold_prefix
from engram_core.application.dto import (
    CreateMemoryInput,
    EditMemoryInput,
    UpdateAttributesInput,
)
from engram_core.domain import scoring
from engram_core.domain.errors import NotFoundError, StaleVersionError
from engram_core.domain.kinds import KindRegistry
from engram_core.domain.memory import Memory
from engram_core.domain.ports import Clock, MemoryRepository
from engram_core.domain.values import (
    EvidenceRef,
    Lifetime,
    Link,
    LinkRelation,
    MemoryId,
    Slug,
    Visibility,
    derive_slug,
    new_memory_id,
)
from engram_events import EventBus, EventEnvelope, EventStore, Provenance, new_uuid7

_USER_ACTOR = "user"


def _confidence_prior(provenance: Provenance) -> float:
    if provenance.actor == _USER_ACTOR:
        return scoring.CONFIDENCE_PRIOR_USER_STATED
    return scoring.CONFIDENCE_PRIOR_ASSISTANT_INFERRED


class MemoryCommandService:
    """All write operations on memories."""

    def __init__(
        self,
        repository: MemoryRepository,
        bus: EventBus,
        clock: Clock,
        kinds: KindRegistry,
        store: EventStore,
    ) -> None:
        self._repository = repository
        self._bus = bus
        self._clock = clock
        self._kinds = kinds
        self._store = store

    # -- creation & content ---------------------------------------------------

    def create_memory(self, input: CreateMemoryInput, provenance: Provenance) -> MemoryId:
        """Create a typed memory; returns its immutable id.

        Attributes are validated against the kind schema; ``confidence=None``
        applies the source prior derived from ``provenance``. Auto-derived slugs
        carry an id suffix so they never collide; an explicitly supplied slug that
        collides surfaces as a StorageError from the projection (a pre-append
        uniqueness check arrives with the API milestone).

        Raises:
            ValidationError: invalid slug/title/attributes/confidence.
        """
        memory_id = new_memory_id()
        slug = (
            Slug(input.slug) if input.slug is not None else derive_slug(input.title, memory_id.hex)
        )
        attributes = self._kinds.parse(
            input.kind,
            dict(input.attributes),
            schema_version=self._kinds.current_version(input.kind),
        )
        payloads = Memory.decide_create(
            memory_id,
            input.kind,
            slug,
            input.title,
            input.content,
            attributes,
            self._kinds,
            tags=input.tags,
            confidence=(
                input.confidence if input.confidence is not None else _confidence_prior(provenance)
            ),
            lifetime=input.lifetime,
            visibility=input.visibility,
        )
        self._commit(memory_id, current_version=0, payloads=payloads, provenance=provenance)
        return memory_id

    def edit_memory(
        self, memory_id: MemoryId, input: EditMemoryInput, provenance: Provenance
    ) -> None:
        """Apply a sparse narrative edit (title/content/slug).

        Raises:
            NotFoundError: unknown or deleted memory.
            StaleVersionError: ``input.expected_version`` is outdated.
        """
        memory = self._load_at(memory_id, input.expected_version)
        payloads = memory.decide_edit(
            title=input.title,
            content=input.content,
            slug=Slug(input.slug) if input.slug is not None else None,
        )
        self._commit(memory_id, memory.version, payloads, provenance)

    def tag_memory(
        self,
        memory_id: MemoryId,
        *,
        add: tuple[str, ...] = (),
        remove: tuple[str, ...] = (),
        provenance: Provenance,
    ) -> None:
        """Add/remove tags."""
        memory = self._repository.load(memory_id)
        self._commit(memory_id, memory.version, memory.decide_tag(add, remove), provenance)

    def archive_memory(
        self, memory_id: MemoryId, reason: str | None, provenance: Provenance
    ) -> None:
        """Archive (soft-hide) a memory."""
        memory = self._repository.load(memory_id)
        self._commit(memory_id, memory.version, memory.decide_archive(reason), provenance)

    def restore_memory(self, memory_id: MemoryId, provenance: Provenance) -> None:
        """Restore an archived memory to active."""
        memory = self._repository.load(memory_id)
        self._commit(memory_id, memory.version, memory.decide_restore(), provenance)

    def delete_memory(
        self, memory_id: MemoryId, reason: str | None, provenance: Provenance
    ) -> None:
        """Append the tombstone. Never called by automation (ADR-0011)."""
        memory = self._repository.load(memory_id)
        self._commit(memory_id, memory.version, memory.decide_delete(reason), provenance)

    def record_access(
        self, memory_id: MemoryId, context: str | None, provenance: Provenance
    ) -> None:
        """Record that a consumer recalled this memory (retention-score input)."""
        memory = self._repository.load(memory_id)
        self._commit(memory_id, memory.version, memory.decide_record_access(context), provenance)

    # -- plumbing ---------------------------------------------------------------

    def _load_at(self, memory_id: MemoryId, expected_version: int) -> Memory:
        memory = self._repository.load(memory_id)
        if memory.version != expected_version:
            raise StaleVersionError(
                f"memory {memory_id}: expected version {expected_version},"
                f" current is {memory.version}"
            )
        return memory

    def _commit(
        self,
        stream_id: MemoryId,
        current_version: int,
        payloads: Sequence[object],
        provenance: Provenance,
    ) -> Sequence[EventEnvelope]:
        if not payloads:
            return ()
        occurred_at = self._clock.now()
        envelopes = [
            EventEnvelope(
                event_id=new_uuid7(),
                stream_id=stream_id,
                stream_seq=current_version + offset + 1,
                event_type=type(payload).__name__,
                schema_version=1,
                payload=payload,
                occurred_at=occurred_at,
                provenance=provenance,
            )
            for offset, payload in enumerate(payloads)
        ]
        appended = self._repository.append(envelopes)
        self._bus.publish(appended)
        return appended

    # -- later milestones (contracts unchanged) ----------------------------------

    def update_attributes(
        self, memory_id: MemoryId, input: UpdateAttributesInput, provenance: Provenance
    ) -> None:
        """Sparse change to kind-schema fields, validated against the KindRegistry.

        Raises:
            StaleVersionError: ``input.expected_version`` is outdated.
            ValidationError: unknown fields or schema violations.
        """
        memory = self._load_at(memory_id, input.expected_version)
        payloads = memory.decide_update_attributes(dict(input.changes), self._kinds)
        self._commit(memory_id, memory.version, payloads, provenance)

    def confirm_memory(self, memory_id: MemoryId, note: str | None, provenance: Provenance) -> None:
        """Vouch for a memory. The confirmer's weight is resolved from the
        scoring policy and provenance, then recorded in the event (ADR-0019)."""
        memory = self._repository.load(memory_id)
        weight = scoring.confirm_weight_for(provenance.actor)
        self._commit(memory_id, memory.version, memory.decide_confirm(weight, note), provenance)

    def contradict_memory(
        self,
        memory_id: MemoryId,
        contradicting_id: MemoryId | None,
        note: str | None,
        provenance: Provenance,
    ) -> None:
        """Dispute a memory; when the disputing memory is named it must exist
        and a ``contradicts`` edge is created alongside (memory-model.md §5).

        Raises:
            NotFoundError: unknown memory, or unknown contradicting memory.
        """
        memory = self._repository.load(memory_id)
        if contradicting_id is not None:
            self._repository.load(contradicting_id)  # existence check
        weight = scoring.contradict_weight_for(provenance.actor)
        payloads = memory.decide_contradict(weight, contradicting_id, note)
        self._commit(memory_id, memory.version, payloads, provenance)

    def add_evidence(
        self, memory_id: MemoryId, evidence: EvidenceRef, provenance: Provenance
    ) -> None:
        """Append supporting evidence (justification spine, append-only)."""
        memory = self._repository.load(memory_id)
        self._commit(memory_id, memory.version, memory.decide_add_evidence(evidence), provenance)

    def adjust_importance(
        self,
        memory_id: MemoryId,
        *,
        pinned: bool | None = None,
        user_weight: float | None = None,
        clear_user_weight: bool = False,
        provenance: Provenance,
    ) -> None:
        """Pin/unpin or set/clear the explicit user weight (importance signal)."""
        memory = self._repository.load(memory_id)
        payloads = memory.decide_adjust_importance(
            pinned=pinned, user_weight=user_weight, clear_user_weight=clear_user_weight
        )
        self._commit(memory_id, memory.version, payloads, provenance)

    def set_visibility(
        self,
        memory_id: MemoryId,
        visibility: Visibility,
        allowed_actors: tuple[str, ...],
        provenance: Provenance,
    ) -> None:
        """Change who may recall this memory."""
        memory = self._repository.load(memory_id)
        payloads = memory.decide_set_visibility(visibility, allowed_actors)
        self._commit(memory_id, memory.version, payloads, provenance)

    def set_lifetime(self, memory_id: MemoryId, lifetime: Lifetime, provenance: Provenance) -> None:
        """Change the retention policy."""
        memory = self._repository.load(memory_id)
        self._commit(memory_id, memory.version, memory.decide_set_lifetime(lifetime), provenance)

    def link_memories(
        self,
        source_id: MemoryId,
        target_id: MemoryId,
        relation: LinkRelation,
        provenance: Provenance,
    ) -> None:
        """Create a typed tier-1 edge (ADR-0010, canonical direction).

        Raises:
            NotFoundError: either end is unknown or deleted.
            ValidationError: self-link.
        """
        source = self._repository.load(source_id)
        self._repository.load(target_id)  # existence check; deleted targets refuse
        payloads = source.decide_link(Link(target_id, relation))
        self._commit(source_id, source.version, payloads, provenance)

    def merge_memories(
        self,
        survivor_id: MemoryId,
        source_id: MemoryId,
        merged_content: str,
        provenance: Provenance,
    ) -> None:
        """Entity resolution merge. Not yet implemented (M5 candidate-generation
        opens proposals only; a direct merge command has no caller yet)."""
        raise NotImplementedError

    def undo_last_change(self, memory_id: MemoryId, provenance: Provenance) -> UUID:
        """Compensate the single most recent event on this stream (ADR-0021);
        returns the compensating event's id.

        Distinct from ``ProposalCommandService.undo_proposal``: that compensates
        a whole merge batch, this compensates one stream's own last change —
        the single-memory case ADR-0021 names.

        Raises:
            NotFoundError: unknown memory.
            ConflictError: no inverse is defined for the last event type (e.g.
                the tombstone itself; delete has no compensator today).
        """
        envelopes = self._store.read_stream(memory_id)
        if not envelopes:
            raise NotFoundError(f"no such memory: {memory_id}")
        last = envelopes[-1]
        prior = fold_prefix(envelopes, len(envelopes) - 1, self._kinds)
        reason = f"undo of {last.event_type} on {memory_id}"
        payload = compensate(last.payload, prior, reason)
        appended = self._commit(memory_id, last.stream_seq, (payload,), provenance)
        return appended[0].event_id
