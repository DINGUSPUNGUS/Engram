"""The SSE generator's own logic (ADR-0023): catch-up from ``Last-Event-ID``,
the resync cap, and idle heartbeats.

Driven directly against ``_stream_body`` rather than through ``TestClient``:
this environment's ASGI transport buffers a response fully before yielding
anything, which hangs forever against a generator that, by design, never
terminates on its own (it tails the log live until the client disconnects).
No existing test in this repo is async, so each test wraps a small coroutine
in ``asyncio.run`` rather than introducing a new pytest-async marker.
"""

import asyncio
import contextlib
from collections.abc import AsyncGenerator
from pathlib import Path

import pytest

from engram_api.config import EngramSettings
from engram_api.routers.v1 import events as events_router
from engram_api.runtime import Runtime, build_runtime
from engram_core.application.dto import CreateMemoryInput
from engram_core.domain.values import MemoryKind
from engram_events import Provenance

USER = Provenance(actor="user")


class _FakeRequest:
    """Enough of ``starlette.Request`` for ``_stream_body``: only disconnection."""

    def __init__(self) -> None:
        self.disconnected = False

    async def is_disconnected(self) -> bool:
        return self.disconnected


async def _collect(agen: AsyncGenerator[str], count: int, request: _FakeRequest) -> list[str]:
    """Pull ``count`` chunks, then signal disconnect and close cleanly —
    proving the ``finally: bus.unsubscribe(...)`` path actually runs."""
    chunks: list[str] = []
    try:
        for _ in range(count):
            chunks.append(await asyncio.wait_for(agen.__anext__(), timeout=5))
    finally:
        request.disconnected = True
        await agen.aclose()
    return chunks


def _runtime(tmp_path: Path) -> Runtime:
    return build_runtime(EngramSettings(data_dir=tmp_path, env="test"))


@pytest.mark.integration
def test_catch_up_replays_missed_events_in_order(tmp_path: Path) -> None:
    runtime = _runtime(tmp_path)
    runtime.commands.create_memory(
        CreateMemoryInput(
            kind=MemoryKind.FACT, title="a", content="", attributes={"statement": "a"}
        ),
        USER,
    )
    runtime.commands.create_memory(
        CreateMemoryInput(
            kind=MemoryKind.FACT, title="b", content="", attributes={"statement": "b"}
        ),
        USER,
    )

    async def scenario() -> list[str]:
        request = _FakeRequest()
        agen = events_router._stream_body(request, runtime.store, runtime.bus, "0")
        return await _collect(agen, 2, request)

    chunks = asyncio.run(scenario())

    assert chunks[0].startswith("id: 1\ndata: ")
    assert chunks[1].startswith("id: 2\ndata: ")
    assert '"event_type":"MemoryCreated"' in chunks[0]
    assert "payload" not in chunks[0]


@pytest.mark.integration
def test_fresh_connect_skips_catch_up_and_delivers_new_events_live(tmp_path: Path) -> None:
    runtime = _runtime(tmp_path)
    runtime.commands.create_memory(
        CreateMemoryInput(
            kind=MemoryKind.FACT, title="before connect", content="", attributes={"statement": "x"}
        ),
        USER,
    )

    async def scenario() -> list[str]:
        request = _FakeRequest()
        agen = events_router._stream_body(request, runtime.store, runtime.bus, None)
        started: asyncio.Task[str] = asyncio.get_running_loop().create_task(agen.__anext__())
        await asyncio.sleep(0.05)  # let the generator subscribe and start waiting
        assert not started.done()  # nothing pre-existing was replayed
        runtime.commands.create_memory(
            CreateMemoryInput(
                kind=MemoryKind.FACT,
                title="after connect",
                content="",
                attributes={"statement": "y"},
            ),
            USER,
        )
        chunk = await asyncio.wait_for(started, timeout=5)
        request.disconnected = True
        await agen.aclose()
        return [chunk]

    chunks = asyncio.run(scenario())

    assert chunks[0].startswith("id: 2\ndata: ")  # seq 1 (pre-existing) was never sent


@pytest.mark.integration
def test_gap_beyond_replay_cap_sends_resync_not_partial_history(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(events_router, "_REPLAY_CAP", 2)
    runtime = _runtime(tmp_path)
    for i in range(4):
        runtime.commands.create_memory(
            CreateMemoryInput(
                kind=MemoryKind.FACT, title=f"m{i}", content="", attributes={"statement": str(i)}
            ),
            USER,
        )

    async def scenario() -> list[str]:
        request = _FakeRequest()
        agen = events_router._stream_body(request, runtime.store, runtime.bus, "0")
        return await _collect(agen, 1, request)

    chunks = asyncio.run(scenario())

    assert chunks == ["event: resync\ndata: {}\n\n"]


@pytest.mark.integration
def test_idle_stream_sends_heartbeats(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(events_router, "_HEARTBEAT_SECONDS", 0.02)
    runtime = _runtime(tmp_path)

    async def scenario() -> list[str]:
        request = _FakeRequest()
        agen = events_router._stream_body(request, runtime.store, runtime.bus, None)
        return await _collect(agen, 2, request)

    chunks = asyncio.run(scenario())

    assert chunks == [": heartbeat\n\n", ": heartbeat\n\n"]


@pytest.mark.integration
def test_disconnect_unsubscribes_from_the_bus(tmp_path: Path) -> None:
    """The resource-cleanup half of the contract: a closed stream must not
    leave its handler on the bus forever (it would fire, uselessly, on every
    future publish for the life of the process)."""
    runtime = _runtime(tmp_path)
    before = len(runtime.bus._handlers)

    async def scenario() -> None:
        request = _FakeRequest()
        agen = events_router._stream_body(request, runtime.store, runtime.bus, None)
        task: asyncio.Task[str] = asyncio.get_running_loop().create_task(agen.__anext__())
        await asyncio.sleep(0.05)
        assert len(runtime.bus._handlers) == before + 1
        # Cancelling the in-flight ``__anext__()`` throws into the generator at
        # its current await point, unwinding through ``finally`` — the same path
        # a real client disconnect drives. A separate ``aclose()`` afterwards
        # would race an already-unwinding generator, so this is the whole story.
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task

    asyncio.run(scenario())

    assert len(runtime.bus._handlers) == before
