"""The Memory aggregate: one mechanism for all twelve kinds (ADR-0008).

Event-sourced: state is a pure fold over the stream's events (``fold``/``evolve``),
and commands (``decide_*``) validate invariants — including kind-schema validation
through the KindRegistry — and return the event payloads to append. They never
mutate anything themselves.

Phase 1 implements the narrative core: create, edit, tag, archive/restore, delete,
record-access. The spine commands (confirm/contradict/evidence/importance/
visibility/lifetime), links, and merge keep their contracts as stubs and land with
their phases.
"""

import dataclasses
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime

from engram_core.domain import events as ev
from engram_core.domain.errors import ConflictError, ValidationError
from engram_core.domain.kinds import KindAttributes, KindRegistry
from engram_core.domain.values import (
    EvidenceRef,
    ImportanceSignals,
    Lifetime,
    Link,
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
            memory = memory.evolve(envelope)
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

    def evolve(self, envelope: EventEnvelope) -> "Memory":
        """Return the state after one more event. Pure.

        Raises:
            ValidationError: event types this phase does not fold yet — replaying
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
                raise ValidationError(
                    f"event type not foldable yet (phase 1): {envelope.event_type}"
                )
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

    # -- later phases (contracts unchanged, bodies land with their phase) -------

    def decide_update_attributes(
        self, changes: dict[str, object], kinds: KindRegistry
    ) -> Sequence[object]:
        """Produce ``MemoryAttributesUpdated`` (phase 3)."""
        raise NotImplementedError

    def decide_confirm(self, note: str | None = None) -> Sequence[object]:
        """Produce ``MemoryConfirmed`` (phase 5)."""
        raise NotImplementedError

    def decide_contradict(
        self, contradicting_id: MemoryId | None = None, note: str | None = None
    ) -> Sequence[object]:
        """Produce ``MemoryContradicted`` (phase 5)."""
        raise NotImplementedError

    def decide_add_evidence(self, evidence: EvidenceRef) -> Sequence[object]:
        """Produce ``MemoryEvidenceAdded`` (phase 5)."""
        raise NotImplementedError

    def decide_adjust_importance(
        self, *, pinned: bool | None = None, user_weight: float | None = None
    ) -> Sequence[object]:
        """Produce ``MemoryImportanceAdjusted`` (phase 5)."""
        raise NotImplementedError

    def decide_set_visibility(
        self, visibility: Visibility, allowed_actors: Sequence[str] = ()
    ) -> Sequence[object]:
        """Produce ``MemoryVisibilityChanged`` (phase 5)."""
        raise NotImplementedError

    def decide_set_lifetime(self, lifetime: Lifetime) -> Sequence[object]:
        """Produce ``MemoryLifetimeChanged`` (phase 5)."""
        raise NotImplementedError

    def decide_link(self, link: Link) -> Sequence[object]:
        """Produce ``MemoryLinked`` (phase 3)."""
        raise NotImplementedError

    def decide_merge_from(self, source: "Memory", merged_content: str) -> Sequence[object]:
        """Produce ``MemoryMerged`` (phase 5)."""
        raise NotImplementedError
