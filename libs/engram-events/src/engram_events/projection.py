"""Projection contract.

A projection folds events into some derived representation: SQLite state tables,
a search index, markdown files. Every projection must be *rebuildable*: replaying
the full log from ``global_seq`` 0 through ``apply`` must deterministically
reproduce its state (this is a CI-tested invariant once implementations land).
"""

from typing import Protocol

from engram_events.envelope import EventEnvelope


class Projection(Protocol):
    """A rebuildable, checkpointed consumer of the event log."""

    @property
    def name(self) -> str:
        """Stable unique name, used as the checkpoint key."""
        ...

    def handles(self, event_type: str) -> bool:
        """Return whether this projection cares about ``event_type``."""
        ...

    def apply(self, envelope: EventEnvelope) -> None:
        """Fold one envelope into the projection's state. Must be idempotent
        per ``global_seq`` so replays and crash-recovery are safe."""
        ...

    def checkpoint(self) -> int:
        """Return the last ``global_seq`` this projection has applied."""
        ...

    def reset(self) -> None:
        """Drop all derived state so the projection can be rebuilt from seq 0."""
        ...
