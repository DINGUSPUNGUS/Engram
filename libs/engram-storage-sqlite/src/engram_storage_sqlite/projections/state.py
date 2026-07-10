"""The state projection: folds memory events into the current-state tables.

Implements the ``Projection`` protocol from engram-events. Must stay deterministic
and idempotent per ``global_seq`` — ``engram rebuild`` replays the whole log
through this class. Stubs.
"""

from sqlalchemy.engine import Engine

from engram_events import EventEnvelope

_HANDLED_PREFIXES = ("Memory",)


class StateProjection:
    """memories / memory_tags / links / projection_checkpoints."""

    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    @property
    def name(self) -> str:
        return "state"

    def handles(self, event_type: str) -> bool:
        return event_type.startswith(_HANDLED_PREFIXES)

    def apply(self, envelope: EventEnvelope) -> None:
        """Fold one event into the state tables and advance the checkpoint
        in the same transaction."""
        raise NotImplementedError

    def checkpoint(self) -> int:
        raise NotImplementedError

    def reset(self) -> None:
        """Truncate all state tables and zero the checkpoint (pre-rebuild)."""
        raise NotImplementedError
