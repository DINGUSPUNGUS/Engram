"""Shared undo plumbing: fold a stream prefix, compute one event's inverse.

Both ``ProposalCommandService.undo_proposal`` (ADR-0018 §3) and
``MemoryCommandService.undo_last_change`` compensate rather than erase — one
inverse event per undone event. The dispatch table lives here once so the two
callers cannot drift on what "undo" means for a given event type.
"""

import dataclasses
from collections.abc import Sequence

from engram_core.domain import events as ev
from engram_core.domain.errors import ConflictError
from engram_core.domain.kinds import KindRegistry
from engram_core.domain.memory import Memory
from engram_events import EventEnvelope


def fold_prefix(stream: Sequence[EventEnvelope], count: int, kinds: KindRegistry) -> Memory | None:
    """State just before event #``count`` (None when compensating the create)."""
    if count == 0:
        return None
    return Memory.fold(list(stream[:count]), kinds)


def compensate(payload: object, prior: Memory | None, reason: str) -> object:
    """The inverse event payload for one applied event (ADR-0018 §3).

    Raises:
        ConflictError: no inverse is defined for this event type — undo refused
            rather than risk silently picking a winner.
    """
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
        case ev.MemoryConfirmed() | ev.MemoryContradicted() if prior is not None:
            # The only producer of MemoryConfidenceRestored (ADR-0019 §2).
            return ev.MemoryConfidenceRestored(
                confidence=prior.confidence,
                last_confirmed_at=prior.last_confirmed_at,
                reason=reason,
            )
        case ev.MemoryImportanceAdjusted() if prior is not None:
            prior_weight = prior.importance.user_weight
            touched_weight = payload.user_weight is not None or payload.clear_user_weight
            return ev.MemoryImportanceAdjusted(
                pinned=prior.importance.pinned if payload.pinned is not None else None,
                user_weight=prior_weight if touched_weight else None,
                clear_user_weight=touched_weight and prior_weight is None,
            )
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
            raise ConflictError(f"no compensator exists for {type(payload).__name__}; undo refused")
