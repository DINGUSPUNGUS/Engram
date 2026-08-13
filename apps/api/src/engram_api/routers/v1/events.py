"""/events — the audit feed (paged by global_seq) and its live tail (ADR-0023).

Both read the raw log directly: there is no projection to compose, so a query
service here would only forward calls (ADR-0007's "map the result", not a new
layer).
"""

import asyncio
from collections.abc import AsyncGenerator, AsyncIterator
from typing import Annotated, Protocol

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import StreamingResponse

from engram_api.dependencies import get_event_bus, get_event_store
from engram_api.schemas.common import PROBLEM_RESPONSES
from engram_api.schemas.events import EventFeedResponse, EventResponse
from engram_core.domain.errors import ConflictError
from engram_events import EventBus, EventEnvelope, EventStore

router = APIRouter(prefix="/events", tags=["events"], responses=PROBLEM_RESPONSES)

Store = Annotated[EventStore, Depends(get_event_store)]
Bus = Annotated[EventBus, Depends(get_event_bus)]

# ADR-0023 §3: beyond this many missed events, a reconnect gets one ``resync``
# signal instead of a partial history — the client re-reads from scratch.
_REPLAY_CAP = 5000
# ADR-0023 §5: keeps intermediaries from closing an idle connection.
_HEARTBEAT_SECONDS = 15.0
# ADR-0023 §5: local-first, single-user — unbounded fan-out is a bug, not a feature.
_MAX_CONCURRENT_STREAMS = 16

_active_streams = 0
_active_streams_lock = asyncio.Lock()


def _to_response(envelope: EventEnvelope) -> EventResponse:
    assert envelope.global_seq is not None, "read from the store always assigns global_seq"
    return EventResponse(
        global_seq=envelope.global_seq,
        event_id=envelope.event_id,
        stream_id=envelope.stream_id,
        stream_seq=envelope.stream_seq,
        event_type=envelope.event_type,
        occurred_at=envelope.occurred_at,
        actor=envelope.provenance.actor,
    )


class _Disconnectable(Protocol):
    """The one thing ``_stream_body`` needs from a request — narrower than the
    full ``starlette.Request`` so tests can drive it without a real one."""

    async def is_disconnected(self) -> bool: ...


def _sse_message(envelope: EventEnvelope) -> str:
    """One invalidation signal: id = global_seq, data = the same shape the
    paginated feed returns. Payloads stay omitted (ADR-0023 §2)."""
    response = _to_response(envelope)
    return f"id: {envelope.global_seq}\ndata: {response.model_dump_json()}\n\n"


@router.get("", response_model=EventFeedResponse)
async def event_feed(
    store: Store,
    after: Annotated[int, Query(ge=0, description="Return events after this global_seq")] = 0,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
) -> EventFeedResponse:
    """Everything that happened, in order. Payloads are omitted here; use the
    memory timeline endpoint for payload-level history of one memory."""
    envelopes = store.read_all(after_global_seq=after, limit=limit)
    next_after = envelopes[-1].global_seq if len(envelopes) == limit else None
    return EventFeedResponse(items=[_to_response(e) for e in envelopes], next_after=next_after)


async def _stream_body(
    request: _Disconnectable, store: EventStore, bus: EventBus, last_event_id: str | None
) -> AsyncGenerator[str]:
    """Subscribe first, catch up second — any event published in between is
    still captured by the queue and simply re-covered by the catch-up read;
    the monotonic ``after`` cursor drops the resulting duplicate (ADR-0023 §4)."""
    loop = asyncio.get_running_loop()
    queue: asyncio.Queue[EventEnvelope] = asyncio.Queue()

    def _on_publish(envelope: EventEnvelope) -> None:
        loop.call_soon_threadsafe(queue.put_nowait, envelope)

    bus.subscribe(_on_publish)
    try:
        after = 0
        if last_event_id is not None:
            try:
                after = int(last_event_id)
            except ValueError:
                after = 0
            catchup = store.read_all(after_global_seq=after, limit=_REPLAY_CAP + 1)
            if len(catchup) > _REPLAY_CAP:
                # Told to re-read from scratch through the normal read models
                # rather than served a partial history (ADR-0023 §3).
                yield "event: resync\ndata: {}\n\n"
                after = catchup[-1].global_seq or after
            else:
                for envelope in catchup:
                    yield _sse_message(envelope)
                    after = envelope.global_seq or after
        # else: fresh connect, no catch-up — the dashboard already loaded
        # current state through the normal endpoints; only reconnects replay.

        while True:
            if await request.is_disconnected():
                return
            try:
                envelope = await asyncio.wait_for(queue.get(), timeout=_HEARTBEAT_SECONDS)
            except TimeoutError:
                yield ": heartbeat\n\n"
                continue
            if envelope.global_seq is not None and envelope.global_seq > after:
                after = envelope.global_seq
                yield _sse_message(envelope)
    finally:
        bus.unsubscribe(_on_publish)


@router.get("/stream")
async def event_stream(request: Request, store: Store, bus: Bus) -> StreamingResponse:
    """Live invalidation signals over the event feed (ADR-0023).

    A message is a signal, not state — it carries the same ``EventResponse``
    shape the paginated feed returns, payloads omitted. Clients react by
    re-reading the affected projection through the normal endpoints; they must
    never fold pushed events into local state (ADR-0021's rule, applied here).

    Reconnects send ``Last-Event-ID``; the browser's own ``EventSource`` does
    this automatically from the last ``id:`` it saw. One stream per dashboard
    session, shared across views — concurrent streams are capped per process.
    """
    global _active_streams
    async with _active_streams_lock:
        if _active_streams >= _MAX_CONCURRENT_STREAMS:
            raise ConflictError(
                f"too many concurrent event streams open (max {_MAX_CONCURRENT_STREAMS} per"
                " process) — this is a local-first, single-user system; close another tab"
            )
        _active_streams += 1

    last_event_id = request.headers.get("last-event-id")

    async def _generator() -> AsyncIterator[str]:
        global _active_streams
        try:
            async for chunk in _stream_body(request, store, bus, last_event_id):
                yield chunk
        finally:
            async with _active_streams_lock:
                _active_streams -= 1

    return StreamingResponse(
        _generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
