"""Event bus contract and the default in-process implementation.

The bus is for *writes fanning out to projections* — it is not a general RPC
mechanism. Reads never go through the bus (ADR-0004). The default implementation is
synchronous and in-order: when ``publish`` returns, every projection has seen the
events. Async/queued buses are a future optimization behind the same protocol.
"""

import contextlib
from collections.abc import Callable, Sequence
from typing import Protocol

from engram_events.envelope import EventEnvelope

EventHandler = Callable[[EventEnvelope], None]


class EventBus(Protocol):
    """Publish/subscribe contract for event distribution."""

    def publish(self, envelopes: Sequence[EventEnvelope]) -> None:
        """Deliver envelopes, in order, to every subscriber."""
        ...

    def subscribe(self, handler: EventHandler) -> None:
        """Register a handler that receives every published envelope."""
        ...

    def unsubscribe(self, handler: EventHandler) -> None:
        """Remove a handler registered via ``subscribe``. A no-op if it is not
        currently registered (idempotent, so callers need no guard on cleanup)."""
        ...


class InProcessEventBus:
    """Synchronous, in-order, in-process bus. The local-first default."""

    def __init__(self) -> None:
        self._handlers: list[EventHandler] = []

    def publish(self, envelopes: Sequence[EventEnvelope]) -> None:
        for envelope in envelopes:
            for handler in self._handlers:
                handler(envelope)

    def subscribe(self, handler: EventHandler) -> None:
        self._handlers.append(handler)

    def unsubscribe(self, handler: EventHandler) -> None:
        with contextlib.suppress(ValueError):  # already gone — cleanup is idempotent
            self._handlers.remove(handler)
