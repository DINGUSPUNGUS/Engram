"""The Memory aggregate: one mechanism for all twelve kinds (ADR-0008).

Event-sourced: state is a pure fold over the stream's events (``fold``/``evolve``),
and commands (``decide_*``) validate invariants — including kind-schema validation
through the KindRegistry — and return the event payloads to append. They never
mutate anything themselves.

M1 implemented the narrative core: create, edit, tag, archive/restore, delete,
record-access. M3 added links and evidence (portability demands they exist in the
log). The remaining spine commands (confirm/contradict/importance/visibility/
lifetime) and merge keep their contracts as stubs and land with M4.
"""

import dataclasses
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime

from engram_core.domain import events as ev
from engram_core.domain import scoring
from engram_core.domain.errors import ConflictError, ValidationError
from engram_core.domain.kinds import KindAttributes, KindRegistry
from engram_core.domain.values import (
    EvidenceRef,
    EvidenceType,
    ImportanceSignals,
    Lifetime,
    Link,
    LinkRelation,
    MemoryId,
    MemoryKind,
    RetentionPolicy,
    Slug,
    Visibility,
    validate_confidence,
)
from engram_events import EventEnvelope

_TITLE_MAX_LENGTH = 500


def _normalize_tags(tags: Sequence[str]) -> tuple[str, ...]:
    seen: dict[str, None] = {}
    for tag in tags:
        normalized = tag.strip().lower()
        if normalized:
            seen[normalized] = None
    return tuple(seen)


def _validate_title(title: str) -> str:
    stripped = title.strip()
    if not stripped:
        raise ValidationError("title must not be empty")
    if len(stripped) > _TITLE_MAX_LENGTH:
        raise ValidationError(f"title longer than {_TITLE_MAX_LENGTH} chars")
    return stripped


@dataclass
class Memory:
    """A single remembered thing, folded from its event stream.

    ``version`` equals the last applied ``stream_seq`` and is the optimistic
    concurrency token. ``kind`` is immutable after creation. Staleness is *derived*
    (effective confidence below the kind threshold) and therefore not a field here —
    it lives in the read side.
    """

    id: MemoryId
    kind: MemoryKind
    slug: Slug
    title: str
    content: str
    attributes: KindAttributes
    importance: ImportanceSignals
    confidence: float
    lifetime: Lifetime
    visibility: Visibility
    allowed_actors: tuple[str, ...] = ()
    last_confirmed_at: datetime | None = None
    evidence: tuple[EvidenceRef, ...] = ()
    tags: frozenset[str] = frozenset()
    links: tuple[Link, ...] = ()
    archived: bool = False
    deleted: bool = False
    version: int = 0

    # -- reconstruction (fold) ------------------------------------------------

    @classmethod
    def fold(cls, envelopes: Sequence[EventEnvelope], kinds: KindRegistry) -> "Memory":
        """Rebuild current state by applying every envelope of one stream in order.

        Raises:
            ValidationError: empty stream, wrong first event, or unparseable
                attributes.
        """
        if not envelopes:
            raise ValidationError("cannot fold an empty stream")
        first = envelopes[0]
        if not isinstance(first.payload, ev.MemoryCreated):
            raise ValidationError(f"stream must start with MemoryCreated, got {first.event_type}")
        memory = cls._from_created(first, kinds)
        for envelope in envelopes[1:]:
            memory = memory.evolve(envelope, kinds=kinds)
        return memory

    @classmethod
    def _from_created(cls, envelope: EventEnvelope, kinds: KindRegistry) -> "Memory":
        payload = envelope.payload
        assert isinstance(payload, ev.MemoryCreated)
        kind = MemoryKind(payload.kind)
        attributes = kinds.parse(
            kind, dict(payload.attributes), schema_version=payload.attributes_schema_version
        )
        return cls(
            id=MemoryId(payload.memory_id),
            kind=kind,
            slug=Slug(payload.slug),
            title=payload.title,
            content=payload.content,
            attributes=attributes,
            importance=ImportanceSignals(created_at=envelope.occurred_at),
            confidence=validate_confidence(payload.confidence),
            lifetime=Lifetime(RetentionPolicy(payload.lifetime_policy), payload.lifetime_until),
            visibility=Visibility(payload.visibility),
            tags=frozenset(payload.tags),
            version=envelope.stream_seq,
        )

    def evolve(self, envelope: EventEnvelope, *, kinds: KindRegistry | None = None) -> "Memory":
        """Return the state after one more event. Pure.

        ``kinds`` is required only to fold ``MemoryAttributesUpdated`` — attributes
        are schema-governed, so folding them needs the schema registry (``fold``
        always passes it).

        Raises:
            ValidationError: event types the aggregate does not fold yet — replaying
                them silently would corrupt state.
        """
        payload = envelope.payload
        changes: dict[str, object]
        match payload:
            case ev.MemoryEdited():
                changes = {}
                if payload.title is not None:
                    changes["title"] = payload.title
                if payload.content is not None:
                    changes["content"] = payload.content
                if payload.slug is not None:
                    changes["slug"] = Slug(payload.slug)
            case ev.MemoryTagged():
                changes = {"tags": (self.tags | set(payload.added)) - set(payload.removed)}
            case ev.MemoryLinked():
                link = Link(MemoryId(payload.target_id), LinkRelation(payload.relation))
                changes = {"links": (*self.links, link)} if link not in self.links else {}
            case ev.MemoryUnlinked():
                gone = Link(MemoryId(payload.target_id), LinkRelation(payload.relation))
                changes = {"links": tuple(link for link in self.links if link != gone)}
            case ev.MemoryConfirmed():
                changes = {
                    "confidence": scoring.confirm_confidence(self.confidence, payload.weight),
                    "last_confirmed_at": envelope.occurred_at,
                }
            case ev.MemoryContradicted():
                changes = {
                    "confidence": scoring.contradict_confidence(self.confidence, payload.weight)
                }
            case ev.MemoryConfidenceRestored():
                changes = {
                    "confidence": payload.confidence,
                    "last_confirmed_at": payload.last_confirmed_at,
                }
            case ev.MemoryImportanceAdjusted():
                signals = self.importance
                if payload.pinned is not None:
                    signals = dataclasses.replace(signals, pinned=payload.pinned)
                if payload.clear_user_weight:
                    signals = dataclasses.replace(signals, user_weight=None)
                elif payload.user_weight is not None:
                    signals = dataclasses.replace(signals, user_weight=payload.user_weight)
                changes = {"importance": signals}
            case ev.MemoryEvidenceAdded():
                added = EvidenceRef(
                    EvidenceType(payload.evidence_type), payload.value, payload.note
                )
                changes = {"evidence": (*self.evidence, added)}
            case ev.MemoryEvidenceRetracted():
                if not 1 <= payload.seq <= len(self.evidence):
                    raise ValidationError(
                        f"cannot retract evidence #{payload.seq}:"
                        f" only {len(self.evidence)} entries exist"
                    )
                remaining = tuple(
                    item for index, item in enumerate(self.evidence, 1) if index != payload.seq
                )
                changes = {"evidence": remaining}
            case ev.MemoryAttributesUpdated():
                if kinds is None:
                    raise ValidationError(
                        "folding MemoryAttributesUpdated requires the kind registry"
                    )
                merged = dataclasses.asdict(self.attributes) | dict(payload.changes)
                changes = {
                    "attributes": kinds.parse(
                        self.kind, merged, schema_version=payload.attributes_schema_version
                    )
                }
            case ev.MemoryVisibilityChanged():
                changes = {
                    "visibility": Visibility(payload.visibility),
                    "allowed_actors": tuple(payload.allowed_actors),
                }
            case ev.MemoryLifetimeChanged():
                changes = {
                    "lifetime": Lifetime(
                        RetentionPolicy(payload.lifetime_policy), payload.lifetime_until
                    )
                }
            case ev.MemoryArchived():
                changes = {"archived": True}
            case ev.MemoryRestored():
                changes = {"archived": False}
            case ev.MemoryDeleted():
                changes = {"deleted": True}
            case ev.MemoryAccessed():
                changes = {
                    "importance": dataclasses.replace(
                        self.importance,
                        last_accessed_at=envelope.occurred_at,
                        access_count=self.importance.access_count + 1,
                    )
                }
            case _:
                raise ValidationError(f"event type not foldable yet: {envelope.event_type}")
        return dataclasses.replace(self, version=envelope.stream_seq, **changes)  # type: ignore[arg-type]

    # -- guards -----------------------------------------------------------------

    def _require_live(self) -> None:
        if self.deleted:
            raise ConflictError(f"memory {self.id} is deleted")

    def _require_editable(self) -> None:
        self._require_live()
        if self.archived:
            raise ConflictError(f"memory {self.id} is archived; restore it first")

    # -- commands (decide) ----------------------------------------------------

    @staticmethod
    def decide_create(
        memory_id: MemoryId,
        kind: MemoryKind,
        slug: Slug,
        title: str,
        content: str,
        attributes: KindAttributes,
        kinds: KindRegistry,
        *,
        tags: Sequence[str] = (),
        confidence: float | None = None,
        lifetime: Lifetime | None = None,
        visibility: Visibility | None = None,
    ) -> Sequence[object]:
        """Validate and produce ``MemoryCreated``.

        ``confidence=None`` falls back to the assistant-inferred prior; callers
        that know the source (the command service) resolve the prior from
        provenance before calling.
        """
        expected_type = kinds.attributes_type(kind)
        if not isinstance(attributes, expected_type):
            raise ValidationError(
                f"attributes for {kind} must be {expected_type.__name__},"
                f" got {type(attributes).__name__}"
            )
        resolved_lifetime = lifetime if lifetime is not None else Lifetime()
        return (
            ev.MemoryCreated(
                memory_id=memory_id,
                kind=kind.value,
                slug=str(slug),
                title=_validate_title(title),
                content=content,
                attributes=dataclasses.asdict(attributes),
                attributes_schema_version=kinds.current_version(kind),
                tags=_normalize_tags(tags),
                confidence=validate_confidence(0.6 if confidence is None else confidence),
                lifetime_policy=resolved_lifetime.policy.value,
                lifetime_until=resolved_lifetime.until,
                visibility=(visibility or Visibility.SHARED).value,
            ),
        )

    def decide_edit(
        self,
        *,
        title: str | None = None,
        content: str | None = None,
        slug: Slug | None = None,
    ) -> Sequence[object]:
        """Produce ``MemoryEdited`` for the changed narrative fields; no-op edits
        produce no events. ``kind`` is immutable — misclassification is fixed by
        supersede."""
        self._require_editable()
        new_title = None
        if title is not None and _validate_title(title) != self.title:
            new_title = _validate_title(title)
        new_content = content if content is not None and content != self.content else None
        new_slug = str(slug) if slug is not None and slug != self.slug else None
        if new_title is None and new_content is None and new_slug is None:
            return ()
        return (ev.MemoryEdited(title=new_title, content=new_content, slug=new_slug),)

    def decide_tag(self, add: Sequence[str] = (), remove: Sequence[str] = ()) -> Sequence[object]:
        """Produce ``MemoryTagged`` after normalizing; already-present adds and
        absent removes are dropped. No effective change produces no events."""
        self._require_editable()
        effective_add = tuple(t for t in _normalize_tags(add) if t not in self.tags)
        effective_remove = tuple(t for t in _normalize_tags(remove) if t in self.tags)
        if not effective_add and not effective_remove:
            return ()
        return (ev.MemoryTagged(added=effective_add, removed=effective_remove),)

    def decide_archive(self, reason: str | None = None) -> Sequence[object]:
        """Produce ``MemoryArchived``."""
        self._require_live()
        if self.archived:
            raise ConflictError(f"memory {self.id} is already archived")
        return (ev.MemoryArchived(reason=reason),)

    def decide_restore(self) -> Sequence[object]:
        """Produce ``MemoryRestored``."""
        self._require_live()
        if not self.archived:
            raise ConflictError(f"memory {self.id} is not archived")
        return (ev.MemoryRestored(),)

    def decide_delete(self, reason: str | None = None) -> Sequence[object]:
        """Produce the ``MemoryDeleted`` tombstone. Never called by automation
        (ADR-0011)."""
        self._require_live()
        return (ev.MemoryDeleted(reason=reason),)

    def decide_record_access(self, context: str | None = None) -> Sequence[object]:
        """Produce ``MemoryAccessed`` (retention-score input)."""
        self._require_live()
        return (ev.MemoryAccessed(context=context),)

    # -- later milestones (contracts unchanged, bodies land with M4) ------------

    def decide_update_attributes(
        self, changes: dict[str, object], kinds: KindRegistry
    ) -> Sequence[object]:
        """Produce ``MemoryAttributesUpdated`` for a sparse, schema-validated change.
        Changes that leave every field equal produce no events.

        Raises:
            ValidationError: unknown fields or values violating the kind schema.
        """
        self._require_editable()
        if not changes:
            return ()
        current = dataclasses.asdict(self.attributes)
        unknown = sorted(set(changes) - set(current))
        if unknown:
            raise ValidationError(f"unknown {self.kind.value} attribute(s): {', '.join(unknown)}")
        merged = current | dict(changes)
        kinds.parse(self.kind, merged, schema_version=kinds.current_version(self.kind))
        effective = {key: value for key, value in changes.items() if current[key] != value}
        if not effective:
            return ()
        return (
            ev.MemoryAttributesUpdated(
                changes=effective,
                attributes_schema_version=kinds.current_version(self.kind),
            ),
        )

    def decide_confirm(self, weight: float, note: str | None = None) -> Sequence[object]:
        """Produce ``MemoryConfirmed``. ``weight`` is the confirmer's weight,
        resolved from the scoring policy by the caller (ADR-0019 — the resolved
        magnitude is recorded so replay never depends on live config).

        Raises:
            ValidationError: weight outside [0,1].
        """
        self._require_live()
        if not 0.0 <= weight <= 1.0:
            raise ValidationError(f"confirmation weight out of [0,1]: {weight}")
        return (ev.MemoryConfirmed(note=note, weight=weight),)

    def decide_contradict(
        self,
        weight: float,
        contradicting_id: MemoryId | None = None,
        note: str | None = None,
    ) -> Sequence[object]:
        """Produce ``MemoryContradicted`` plus, when the disputing memory is
        named and not yet linked, the companion ``contradicts`` edge
        (memory-model.md §5).

        Raises:
            ValidationError: weight outside [0,1], or self-contradiction.
        """
        self._require_live()
        if not 0.0 <= weight <= 1.0:
            raise ValidationError(f"contradiction weight out of [0,1]: {weight}")
        if contradicting_id == self.id:
            raise ValidationError("a memory cannot contradict itself")
        payloads: list[object] = [
            ev.MemoryContradicted(contradicting_id=contradicting_id, note=note, weight=weight)
        ]
        if contradicting_id is not None:
            edge = Link(contradicting_id, LinkRelation.CONTRADICTS)
            if edge not in self.links:
                payloads.append(
                    ev.MemoryLinked(target_id=contradicting_id, relation=edge.relation.value)
                )
        return tuple(payloads)

    def decide_add_evidence(self, evidence: EvidenceRef) -> Sequence[object]:
        """Produce ``MemoryEvidenceAdded``. Evidence is append-only — corrections
        add more evidence, never rewrite it (memory-model.md §3)."""
        self._require_live()
        return (
            ev.MemoryEvidenceAdded(
                evidence_type=evidence.evidence_type.value,
                value=evidence.value,
                note=evidence.note,
            ),
        )

    def decide_adjust_importance(
        self,
        *,
        pinned: bool | None = None,
        user_weight: float | None = None,
        clear_user_weight: bool = False,
    ) -> Sequence[object]:
        """Produce ``MemoryImportanceAdjusted``; no-op adjustments produce no
        events. ``clear_user_weight`` resets the explicit weight to unset.

        Raises:
            ValidationError: user_weight outside [0,1], weight both set and
                cleared, or nothing requested.
        """
        self._require_live()
        if user_weight is not None and clear_user_weight:
            raise ValidationError("cannot set and clear user_weight in one adjustment")
        if user_weight is not None and not 0.0 <= user_weight <= 1.0:
            raise ValidationError(f"user_weight out of [0,1]: {user_weight}")
        if pinned is None and user_weight is None and not clear_user_weight:
            raise ValidationError("importance adjustment requests no change")
        effective_pin = pinned if pinned is not None and pinned != self.importance.pinned else None
        wants_clear = clear_user_weight and self.importance.user_weight is not None
        new_weight = (
            user_weight
            if user_weight is not None and user_weight != self.importance.user_weight
            else None
        )
        if effective_pin is None and new_weight is None and not wants_clear:
            return ()
        return (
            ev.MemoryImportanceAdjusted(
                pinned=effective_pin, user_weight=new_weight, clear_user_weight=wants_clear
            ),
        )

    def decide_set_visibility(
        self, visibility: Visibility, allowed_actors: Sequence[str] = ()
    ) -> Sequence[object]:
        """Produce ``MemoryVisibilityChanged``; no-op when nothing changes.

        Raises:
            ValidationError: allowed_actors given for a non-restricted visibility.
        """
        self._require_live()
        actors = tuple(allowed_actors)
        if actors and visibility is not Visibility.RESTRICTED:
            raise ValidationError("allowed_actors applies only to restricted visibility")
        if visibility is self.visibility and actors == self.allowed_actors:
            return ()
        return (ev.MemoryVisibilityChanged(visibility=visibility.value, allowed_actors=actors),)

    def decide_set_lifetime(self, lifetime: Lifetime) -> Sequence[object]:
        """Produce ``MemoryLifetimeChanged``; no-op when nothing changes."""
        self._require_live()
        if lifetime == self.lifetime:
            return ()
        return (
            ev.MemoryLifetimeChanged(
                lifetime_policy=lifetime.policy.value, lifetime_until=lifetime.until
            ),
        )

    def decide_link(self, link: Link) -> Sequence[object]:
        """Produce ``MemoryLinked`` (tier-1 edge, closed vocabulary — ADR-0010).
        Linking to an already-linked target with the same relation is a no-op.

        Raises:
            ValidationError: self-link.
        """
        self._require_editable()
        if link.target_id == self.id:
            raise ValidationError("a memory cannot link to itself")
        if link in self.links:
            return ()
        return (ev.MemoryLinked(target_id=link.target_id, relation=link.relation.value),)

    def decide_merge_from(self, source: "Memory", merged_content: str) -> Sequence[object]:
        """Produce ``MemoryMerged`` (M4)."""
        raise NotImplementedError
