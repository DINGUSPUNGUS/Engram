"""HTTP-level proof of the P0 concurrency-boundary fix.

``engram_events.OptimisticConcurrencyError`` is a storage-library exception, not
an ``EngramError`` — before the fix it could escape
``engram_storage_sqlite.repositories`` and reach FastAPI unhandled, becoming a
raw 500 instead of the documented 409. This drives a genuine two-writer race
through the real repository/store code (no mocked exception, no simulated
response) and proves the loser gets a typed RFC 9457 409, the winner's write is
the only one on the log, and projections agree with the log afterward.
"""

from collections.abc import Iterator
from pathlib import Path
from typing import TYPE_CHECKING, cast

import pytest
from fastapi.testclient import TestClient

from engram_api.config import EngramSettings
from engram_api.main import create_app
from engram_core.domain.values import MemoryId
from engram_events import EventEnvelope, Provenance, new_uuid7

if TYPE_CHECKING:
    from fastapi import FastAPI

ACTOR_HEADERS = {"X-Engram-Actor": "claude", "X-Engram-Session": "sess-1"}


@pytest.fixture
def client(tmp_path: Path) -> Iterator[TestClient]:
    app = create_app(EngramSettings(data_dir=tmp_path, env="test"))
    with TestClient(app, headers=ACTOR_HEADERS, raise_server_exceptions=False) as test_client:
        yield test_client


@pytest.mark.integration
def test_concurrent_write_conflict_returns_409_problem_json(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Two writers race to append past the same stream position.

    ``confirm`` has no application-layer pre-check (unlike edit/update-attributes,
    which validate ``expected_version`` before ever touching the store) — it is
    exactly the narrow window the P0 finding named: both writers load current
    state, both build a batch against it, and only one storage append can win.
    A second writer is spliced in at the moment this request's repository call
    would otherwise succeed uncontested, so the interleaving is deterministic
    (no real threads, no flakiness) while every other step — the store's unique
    constraint, the ``OptimisticConcurrencyError``, the translation to
    ``StaleVersionError``, the API's exception handler — runs unmodified.
    """
    created = client.post(
        "/api/v1/memories",
        json={
            "kind": "preference",
            "title": "Prefers dark mode",
            "content": "User said they prefer dark mode.",
            "attributes": {"polarity": "likes", "strength": 0.8, "context": "UI"},
            "tags": ["ui"],
            "visibility": "private",
        },
    )
    assert created.status_code == 201, created.text
    memory_id = created.json()["id"]
    stream_id = MemoryId(memory_id)

    runtime = cast("FastAPI", client.app).state.runtime  # populated by the request above
    repository = runtime.commands._repository
    real_append = repository.append
    armed = {"value": True}

    def _steal_position_then_append(
        envelopes: object,
    ) -> object:
        if armed["value"]:
            armed["value"] = False
            target = envelopes[0]  # type: ignore[index]
            competing = EventEnvelope(
                event_id=new_uuid7(),
                stream_id=stream_id,
                stream_seq=target.stream_seq,
                event_type=target.event_type,
                schema_version=target.schema_version,
                payload=target.payload,
                occurred_at=target.occurred_at,
                provenance=Provenance(actor="user", detail="concurrent writer"),
            )
            # append + publish, exactly what the competing writer's own
            # MemoryCommandService._commit would do — not a bare store write.
            appended = runtime.store.append([competing])
            runtime.bus.publish(appended)
        return real_append(envelopes)

    monkeypatch.setattr(repository, "append", _steal_position_then_append)

    response = client.post(f"/api/v1/memories/{memory_id}/confirm", json={"note": "still true"})

    assert response.status_code == 409, response.text
    assert response.headers["content-type"].startswith("application/problem+json")
    body = response.json()
    assert body == {
        "type": "about:blank",
        "title": "Stale version",
        "status": 409,
        "detail": body["detail"],  # exact wording covered at the repository layer
        "instance": f"/api/v1/memories/{memory_id}/confirm",
    }

    # No partial batch: the log holds exactly the create + the winner's
    # confirm — nothing from the request that lost the race landed.
    stream = runtime.store.read_stream(stream_id)
    assert [e.event_type for e in stream] == ["MemoryCreated", "MemoryConfirmed"]

    # Projections agree with the log the race actually produced.
    projected = client.get(f"/api/v1/memories/{memory_id}").json()
    assert projected["version"] == 2

    # Replay is deterministic: rebuilding from the log reproduces the same
    # projected state, with no trace of the rejected request. (Excludes
    # effective_confidence: a query-time decay score derived from elapsed
    # wall-clock time, not from the log — it legitimately differs between two
    # calls made moments apart regardless of replay.)
    runtime.rebuild()
    rebuilt = client.get(f"/api/v1/memories/{memory_id}").json()
    assert {k: v for k, v in rebuilt.items() if k != "effective_confidence"} == {
        k: v for k, v in projected.items() if k != "effective_confidence"
    }
