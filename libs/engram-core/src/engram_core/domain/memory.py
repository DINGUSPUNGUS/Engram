"""The Memory aggregate.

Event-sourced: state is a pure fold over the stream's events (``fold``/``evolve``),
and commands (``decide_*``) validate invariants against current state and return the
event payloads to append — they never mutate anything themselves.

All bodies are intentionally ``NotImplementedError`` stubs: this repository is in
its architecture phase. The signatures and docstrings are the contract.
"""

from collections.abc import Sequence
from dataclasses import dataclass

from engram_core.domain.values import Link, MemoryId, MemoryType, Salience, Slug
from engram_events import EventEnvelope


@dataclass
class Memory:
    """A single remembered thing, folded from its event stream.

    ``version`` equals the last applied ``stream_seq`` and is the optimistic
    concurrency token commands must present when appending.
    """

    id: MemoryId
    slug: Slug
    title: str
    content: str
    memory_type: MemoryType
    salience: Salience
    tags: frozenset[str] = frozenset()
    links: tuple[Link, ...] = ()
    archived: bool = False
    deleted: bool = False
    version: int = 0

    # -- reconstruction (fold) ------------------------------------------------

    @classmethod
    def fold(cls, envelopes: Sequence[EventEnvelope]) -> "Memory":
        """Rebuild current state by applying every envelope of one stream in order.

        The first envelope must be a ``MemoryCreated``.

        Raises:
            ValidationError: if the stream is empty or malformed.
        """
        raise NotImplementedError

    def evolve(self, envelope: EventEnvelope) -> "Memory":
        """Return the state after one more event. Pure — no side effects, total
        over all registered memory event types."""
        raise NotImplementedError

    # -- commands (decide) ----------------------------------------------------
    # Each returns the payload(s) to append; the application layer wraps them in
    # envelopes (ids, seq, provenance, clock) and hands them to the repository.

    @staticmethod
    def decide_create(
        memory_id: MemoryId,
        slug: Slug,
        title: str,
        content: str,
        memory_type: MemoryType,
        tags: Sequence[str] = (),
    ) -> Sequence[object]:
        """Validate and produce ``MemoryCreated``.

        Raises:
            ValidationError: empty title, invalid tags, …
        """
        raise NotImplementedError

    def decide_edit(
        self,
        *,
        title: str | None = None,
        content: str | None = None,
        slug: Slug | None = None,
        memory_type: MemoryType | None = None,
    ) -> Sequence[object]:
        """Produce ``MemoryEdited`` for the changed fields (no-op edits produce
        no events).

        Raises:
            ConflictError: if the memory is deleted or archived.
        """
        raise NotImplementedError

    def decide_tag(self, add: Sequence[str] = (), remove: Sequence[str] = ()) -> Sequence[object]:
        """Produce ``MemoryTagged`` after normalizing and de-duplicating tags."""
        raise NotImplementedError

    def decide_link(self, link: Link) -> Sequence[object]:
        """Produce ``MemoryLinked``.

        Raises:
            ValidationError: on self-links.
            ConflictError: if an identical link already exists.
        """
        raise NotImplementedError

    def decide_merge_from(self, source: "Memory", merged_content: str) -> Sequence[object]:
        """Produce ``MemoryMerged`` on this (surviving) memory. The application
        service is responsible for also archiving the source memory."""
        raise NotImplementedError

    def decide_archive(self, reason: str | None = None) -> Sequence[object]:
        """Produce ``MemoryArchived``."""
        raise NotImplementedError

    def decide_delete(self, reason: str | None = None) -> Sequence[object]:
        """Produce the ``MemoryDeleted`` tombstone."""
        raise NotImplementedError

    def decide_record_access(self, context: str | None = None) -> Sequence[object]:
        """Produce ``MemoryAccessed`` (salience input for future decay)."""
        raise NotImplementedError
