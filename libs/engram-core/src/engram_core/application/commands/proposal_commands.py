"""Proposal command service: PR-style review over memory changes (ADR-0018).

The lifecycle: ``open`` (M3, the importer's front door) → ``approve``/``reject`` →
``merge`` → optionally ``undo``.

Merge is the only event producer: every draft intent is re-driven through the
Memory aggregate's ``decide_*`` methods against the stream's *current* folded
state. Conflicts are detected against stream history — a target whose head moved
past the draft's recorded ``base_version`` raises ``StaleVersionError`` and nothing
is appended. All events of one merge (memory streams + ``ProposalMerged``) go into
one atomic batch.

Undo compensates, never erases: one inverse event per merged event, in reverse
order, plus ``ProposalUndone`` — refused if any affected stream moved since the
merge.
"""

import dataclasses
from collections.abc import Sequence
from datetime import datetime
from uuid import UUID

from engram_core.application.commands import drafts as d
from engram_core.domain import events as ev
from engram_core.domain.errors import (
    ConflictError,
    NotFoundError,
    StaleVersionError,
    ValidationError,
)
from engram_core.domain.kinds import KindRegistry
from engram_core.domain.memory import Memory
from engram_core.domain.ports import Clock, MemoryRepository, ProposalRepository
from engram_core.domain.proposal import Proposal, ProposalStatus
from engram_core.domain.values import (
    EvidenceRef,
    EvidenceType,
    Lifetime,
    Link,
    LinkRelation,
    MemoryId,
    MemoryKind,
    ProposalId,
    RetentionPolicy,
    Slug,
    Visibility,
    new_proposal_id,
)
from engram_events import EventBus, EventEnvelope, EventStore, Provenance, new_uuid7


class _StreamCursor:
    """One target stream during a merge: evolving state + sequence position."""

    def __init__(self, state: Memory | None, version: int) -> None:
        self.state = state
        self.version = version


class ProposalCommandService:
    """All write operations on proposals."""

    def __init__(
        self,
        proposals: ProposalRepository,
        memories: MemoryRepository,
        bus: EventBus,
        clock: Clock,
        kinds: KindRegistry,
        store: EventStore,
    ) -> None:
        self._proposals = proposals
        self._memories = memories
        self._bus = bus
        self._clock = clock
        self._kinds = kinds
        self._store = store

    # -- lifecycle ---------------------------------------------------------------

    def open_proposal(
        self,
        title: str,
        description: str,
        proposed_events: Sequence[dict[str, object]],
        provenance: Provenance,
    ) -> ProposalId:
        """Open a proposal carrying draft intents (ADR-0018).

        This is the only door automation and imports have into memory (ADR-0011).

        Raises:
            ValidationError: empty title, no drafts, or malformed drafts.
        """
        d.parse_all(proposed_events)  # validate the wire form up front
        proposal_id = new_proposal_id()
        payloads = Proposal.decide_open(proposal_id, title, description, proposed_events)
        self._append_to_proposal(proposal_id, 0, payloads, provenance)
        return proposal_id

    def approve_proposal(
        self, proposal_id: ProposalId, note: str | None, provenance: Provenance
    ) -> None:
        """Mark an open proposal approved (does not merge — two explicit steps)."""
        proposal = self._proposals.load(proposal_id)
        self._append_to_proposal(
            proposal_id, proposal.version, proposal.decide_approve(note), provenance
        )

    def reject_proposal(
        self, proposal_id: ProposalId, note: str | None, provenance: Provenance
    ) -> None:
        """Reject an open proposal. Its drafts never become events."""
        proposal = self._proposals.load(proposal_id)
        self._append_to_proposal(
            proposal_id, proposal.version, proposal.decide_reject(note), provenance
        )

    def merge_proposal(self, proposal_id: ProposalId, provenance: Provenance) -> tuple[UUID, ...]:
        """Execute an approved proposal; returns the appended memory-event ids.

        Every intent is re-validated by the aggregate against current state;
        conflict detection compares stream heads to each draft's ``base_version``
        (event history, not projections). The whole merge is one atomic append.

        Raises:
            ConflictError: proposal not approved, or a create target already exists.
            StaleVersionError: a target stream moved since the proposal was opened.
            NotFoundError / ValidationError: what any live command would raise.
        """
        proposal = self._proposals.load(proposal_id)
        intents = d.parse_all(proposal.proposed_events)
        occurred_at = self._clock.now()
        cursors = self._conflict_checked_cursors(intents)

        memory_envelopes: list[EventEnvelope] = []
        for intent in intents:
            cursor = cursors[intent.stream_id]
            payloads = self._decide(intent, cursor, cursors)
            for payload in payloads:
                envelope = self._envelope(
                    intent.stream_id, cursor.version + 1, payload, provenance, occurred_at
                )
                memory_envelopes.append(envelope)
                cursor.version += 1
                cursor.state = (
                    cursor.state.evolve(envelope, kinds=self._kinds)
                    if cursor.state is not None
                    else Memory.fold([envelope], self._kinds)
                )

        appended_ids = tuple(envelope.event_id for envelope in memory_envelopes)
        merged_payloads = proposal.decide_merge(appended_ids)
        proposal_envelopes = [
            self._envelope(
                proposal_id, proposal.version + offset + 1, payload, provenance, occurred_at
            )
            for offset, payload in enumerate(merged_payloads)
        ]
        # One atomic batch: the merge happens completely or not at all.
        appended = self._proposals.append([*memory_envelopes, *proposal_envelopes])
        self._bus.publish(appended)
        return appended_ids

    def undo_proposal(
        self, proposal_id: ProposalId, note: str | None, provenance: Provenance
    ) -> tuple[UUID, ...]:
        """Compensate a merged proposal (ADR-0018 §3); returns compensating ids.

        Raises:
            ConflictError: proposal not merged, or an affected stream moved since
                the merge (undo never silently picks winners).
        """
        proposal = self._proposals.load(proposal_id)
        if proposal.status is not ProposalStatus.MERGED:
            raise ConflictError(
                f"proposal {proposal_id} is {proposal.status.value}; only merged proposals undo"
            )
        if not proposal.merged_event_ids:
            raise ConflictError(f"proposal {proposal_id} recorded no merged events to undo")

        merged_ids = set(proposal.merged_event_ids)
        streams = self._affected_streams(merged_ids)
        occurred_at = self._clock.now()

        compensating: list[EventEnvelope] = []
        heads: dict[UUID, int] = {}
        # Reverse global order: later effects are compensated first.
        flat = sorted(
            (
                envelope
                for envelopes in streams.values()
                for envelope in envelopes
                if envelope.event_id in merged_ids
            ),
            key=lambda e: e.global_seq or 0,
            reverse=True,
        )
        for envelope in flat:
            stream = streams[envelope.stream_id]
            index = next(i for i, e in enumerate(stream) if e.event_id == envelope.event_id)
            prior = self._fold_prefix(stream, index)
            payload = self._compensator(envelope, prior, proposal_id)
            head = heads.get(envelope.stream_id, stream[-1].stream_seq)
            compensating.append(
                self._envelope(envelope.stream_id, head + 1, payload, provenance, occurred_at)
            )
            heads[envelope.stream_id] = head + 1

        undone_payloads = proposal.decide_undo(tuple(e.event_id for e in compensating), note=note)
        proposal_envelopes = [
            self._envelope(
                proposal_id, proposal.version + offset + 1, payload, provenance, occurred_at
            )
            for offset, payload in enumerate(undone_payloads)
        ]
        appended = self._proposals.append([*compensating, *proposal_envelopes])
        self._bus.publish(appended)
        return tuple(e.event_id for e in compensating)

    # -- merge plumbing ------------------------------------------------------------

    def _conflict_checked_cursors(
        self, intents: Sequence[d.DraftIntent]
    ) -> dict[UUID, _StreamCursor]:
        """Load every target stream once; detect conflicts against its history."""
        cursors: dict[UUID, _StreamCursor] = {}
        for intent in intents:
            stream_id = intent.stream_id
            if stream_id in cursors:
                continue
            envelopes = self._store.read_stream(stream_id)
            if isinstance(intent, d.CreateMemoryDraft):
                if envelopes:
                    raise ConflictError(
                        f"cannot create memory {stream_id}: the stream already exists"
                    )
                cursors[stream_id] = _StreamCursor(None, 0)
                continue
            if not envelopes:
                raise NotFoundError(f"draft targets unknown memory: {stream_id}")
            state = Memory.fold(envelopes, self._kinds)
            if intent.base_version is not None and state.version != intent.base_version:
                raise StaleVersionError(
                    f"conflict: memory {stream_id} is at version {state.version},"
                    f" but the proposal was opened against version {intent.base_version}"
                    " — reject and re-import against current state"
                )
            cursors[stream_id] = _StreamCursor(state, state.version)
        return cursors

    def _decide(
        self,
        intent: d.DraftIntent,
        cursor: _StreamCursor,
        cursors: dict[UUID, _StreamCursor],
    ) -> Sequence[object]:
        """Ask the aggregate. The aggregate's invariants are the merge's law."""
        state = cursor.state
        match intent:
            case d.CreateMemoryDraft():
                return Memory.decide_create(
                    MemoryId(intent.memory_id),
                    _kind(intent.kind),
                    Slug(intent.slug),
                    intent.title,
                    intent.content,
                    self._kinds.parse(
                        _kind(intent.kind),
                        dict(intent.attributes),
                        schema_version=intent.attributes_schema_version,
                    ),
                    self._kinds,
                    tags=intent.tags,
                    confidence=intent.confidence,
                    lifetime=_lifetime(intent.lifetime_policy, intent.lifetime_until),
                    visibility=Visibility(intent.visibility),
                )
            case _ if state is None:
                raise NotFoundError(f"draft targets unknown memory: {intent.stream_id}")
            case d.EditMemoryDraft():
                return state.decide_edit(
                    title=intent.title,
                    content=intent.content,
                    slug=Slug(intent.slug) if intent.slug is not None else None,
                )
            case d.TagMemoryDraft():
                return state.decide_tag(intent.add, intent.remove)
            case d.UpdateAttributesDraft():
                return state.decide_update_attributes(dict(intent.changes), self._kinds)
            case d.LinkDraft():
                self._require_target(intent.target_id, cursors)
                return state.decide_link(
                    Link(MemoryId(intent.target_id), LinkRelation(intent.relation))
                )
            case d.UnlinkDraft():
                gone = Link(MemoryId(intent.target_id), LinkRelation(intent.relation))
                if gone not in state.links:
                    return ()
                return (ev.MemoryUnlinked(target_id=intent.target_id, relation=intent.relation),)
            case d.AddEvidenceDraft():
                return state.decide_add_evidence(
                    EvidenceRef(EvidenceType(intent.evidence_type), intent.value, intent.note)
                )
            case d.SetVisibilityDraft():
                return state.decide_set_visibility(
                    Visibility(intent.visibility), intent.allowed_actors
                )
            case d.SetLifetimeDraft():
                return state.decide_set_lifetime(
                    _lifetime(intent.lifetime_policy, intent.lifetime_until)
                )
        raise ValidationError(f"unhandled draft intent: {type(intent).__name__}")

    def _require_target(self, target_id: UUID, cursors: dict[UUID, _StreamCursor]) -> None:
        cursor = cursors.get(target_id)
        if cursor is not None and cursor.state is not None:
            return  # created or loaded earlier in this merge
        if not self._store.read_stream(target_id):
            raise NotFoundError(f"link target does not exist: {target_id}")

    # -- undo plumbing ---------------------------------------------------------------

    def _affected_streams(self, merged_ids: set[UUID]) -> dict[UUID, Sequence[EventEnvelope]]:
        """Locate the merged events; enforce that nothing happened after them."""
        streams: dict[UUID, Sequence[EventEnvelope]] = {}
        remaining = set(merged_ids)
        # The merged events' stream ids are discoverable from the log itself:
        # walk forward until every id is found (bounded by the log size).
        after = 0
        while remaining:
            batch = self._store.read_all(after_global_seq=after, limit=500)
            if not batch:
                raise NotFoundError(
                    f"merged events not found in the log: {sorted(map(str, remaining))[:3]}"
                )
            for envelope in batch:
                if envelope.event_id in remaining:
                    remaining.discard(envelope.event_id)
                    if envelope.stream_id not in streams:
                        streams[envelope.stream_id] = self._store.read_stream(envelope.stream_id)
            last = batch[-1].global_seq
            assert last is not None
            after = last
        for stream_id, envelopes in streams.items():
            trailing = [e for e in envelopes if e.event_id not in merged_ids]
            last_foreign = trailing[-1] if trailing else None
            last_merged = max(
                (e.stream_seq for e in envelopes if e.event_id in merged_ids), default=0
            )
            if last_foreign is not None and last_foreign.stream_seq > last_merged:
                raise ConflictError(
                    f"cannot undo: memory {stream_id} changed after the merge"
                    " — undoing around later changes would silently pick winners"
                )
        return streams

    def _fold_prefix(self, stream: Sequence[EventEnvelope], count: int) -> Memory | None:
        """State just before event #count (None when compensating the create)."""
        if count == 0:
            return None
        return Memory.fold(list(stream[:count]), self._kinds)

    def _compensator(
        self, envelope: EventEnvelope, prior: Memory | None, proposal_id: ProposalId
    ) -> object:
        """The inverse event payload (ADR-0018 §3)."""
        payload = envelope.payload
        reason = f"undo of proposal {proposal_id}"
        match payload:
            case ev.MemoryCreated():
                return ev.MemoryDeleted(reason=reason)
            case ev.MemoryEdited() if prior is not None:
                return ev.MemoryEdited(
                    title=prior.title if payload.title is not None else None,
                    content=prior.content if payload.content is not None else None,
                    slug=str(prior.slug) if payload.slug is not None else None,
                )
            case ev.MemoryTagged():
                return ev.MemoryTagged(added=payload.removed, removed=payload.added)
            case ev.MemoryAttributesUpdated() if prior is not None:
                before = dataclasses.asdict(prior.attributes)
                return ev.MemoryAttributesUpdated(
                    changes={key: before.get(key) for key in payload.changes},
                    attributes_schema_version=payload.attributes_schema_version,
                )
            case ev.MemoryLinked():
                return ev.MemoryUnlinked(target_id=payload.target_id, relation=payload.relation)
            case ev.MemoryUnlinked():
                return ev.MemoryLinked(target_id=payload.target_id, relation=payload.relation)
            case ev.MemoryEvidenceAdded() if prior is not None:
                return ev.MemoryEvidenceRetracted(seq=len(prior.evidence) + 1, reason=reason)
            case ev.MemoryVisibilityChanged() if prior is not None:
                return ev.MemoryVisibilityChanged(
                    visibility=prior.visibility.value, allowed_actors=prior.allowed_actors
                )
            case ev.MemoryLifetimeChanged() if prior is not None:
                return ev.MemoryLifetimeChanged(
                    lifetime_policy=prior.lifetime.policy.value,
                    lifetime_until=prior.lifetime.until,
                )
            case ev.MemoryArchived():
                return ev.MemoryRestored()
            case ev.MemoryRestored():
                return ev.MemoryArchived(reason=reason)
            case _:
                raise ConflictError(
                    f"no compensator exists for {envelope.event_type}; undo refused"
                )

    # -- shared plumbing ---------------------------------------------------------------

    def _append_to_proposal(
        self,
        proposal_id: ProposalId,
        current_version: int,
        payloads: Sequence[object],
        provenance: Provenance,
    ) -> None:
        if not payloads:
            return
        occurred_at = self._clock.now()
        envelopes = [
            self._envelope(
                proposal_id, current_version + offset + 1, payload, provenance, occurred_at
            )
            for offset, payload in enumerate(payloads)
        ]
        appended = self._proposals.append(envelopes)
        self._bus.publish(appended)

    @staticmethod
    def _envelope(
        stream_id: UUID,
        stream_seq: int,
        payload: object,
        provenance: Provenance,
        occurred_at: datetime,
    ) -> EventEnvelope:
        return EventEnvelope(
            event_id=new_uuid7(),
            stream_id=stream_id,
            stream_seq=stream_seq,
            event_type=type(payload).__name__,
            schema_version=1,
            payload=payload,
            occurred_at=occurred_at,
            provenance=provenance,
        )


def _kind(value: str) -> MemoryKind:
    try:
        return MemoryKind(value)
    except ValueError:
        raise ValidationError(f"unknown kind in draft: {value!r}") from None


def _lifetime(policy: str, until: str | None) -> Lifetime:
    parsed = datetime.fromisoformat(until.replace("Z", "+00:00")) if until is not None else None
    try:
        return Lifetime(RetentionPolicy(policy), parsed)
    except ValueError:
        raise ValidationError(f"unknown lifetime policy in draft: {policy!r}") from None
