"""/search (ADR-0016 over HTTP) and /events — the paginated feed, plus the one
``/events/stream`` behavior a normal client call can assert (cap-exceeded is a
plain synchronous 409, raised before any stream body exists). The stream's own
generator logic — catch-up, resync, heartbeats, disconnect cleanup — is
covered in test_event_stream.py, driven directly rather than through
``TestClient`` (see that file's docstring for why)."""

from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from engram_api.config import EngramSettings
from engram_api.main import create_app
from engram_api.routers.v1 import events as events_router

ACTOR_HEADERS = {"X-Engram-Actor": "claude"}


@pytest.fixture
def client(tmp_path: Path) -> Iterator[TestClient]:
    app = create_app(EngramSettings(data_dir=tmp_path, env="test"))
    with TestClient(app, headers=ACTOR_HEADERS, raise_server_exceptions=False) as test_client:
        yield test_client


@pytest.fixture(autouse=True)
def _reset_stream_counter() -> Iterator[None]:
    """The concurrency cap is a process-global by design (ADR-0023 §5: one
    process, not one runtime) — reset it so one test's cleanup timing can
    never leak into another's assertions."""
    events_router._active_streams = 0
    yield
    events_router._active_streams = 0


def _create(client: TestClient, title: str) -> dict[str, object]:
    response = client.post(
        "/api/v1/memories",
        json={"kind": "fact", "title": title, "attributes": {"statement": title}},
    )
    assert response.status_code == 201, response.text
    result: dict[str, object] = response.json()
    return result


# -- /search ----------------------------------------------------------------


@pytest.mark.integration
def test_search_finds_created_memory(client: TestClient) -> None:
    created = _create(client, "engram uses event sourcing")

    response = client.get("/api/v1/search", params={"q": "event sourcing"})

    assert response.status_code == 200, response.text
    hits = response.json()["hits"]
    assert any(hit["memory_id"] == created["id"] for hit in hits)


@pytest.mark.integration
def test_search_malformed_query_is_422(client: TestClient) -> None:
    response = client.get("/api/v1/search", params={"q": "confidence>>0.8"})
    assert response.status_code == 422


# -- /events (the paginated feed) --------------------------------------------


@pytest.mark.integration
def test_event_feed_pages_by_global_seq(client: TestClient) -> None:
    _create(client, "first")
    _create(client, "second")

    first_page = client.get("/api/v1/events", params={"limit": 1}).json()
    assert len(first_page["items"]) == 1
    assert first_page["items"][0]["event_type"] == "MemoryCreated"
    assert first_page["next_after"] == 1

    second_page = client.get(
        "/api/v1/events", params={"after": first_page["next_after"], "limit": 1}
    ).json()
    assert len(second_page["items"]) == 1
    assert second_page["items"][0]["global_seq"] == 2
    # A full page never claims to be the last one without checking again —
    # `next_after` is set whenever exactly `limit` items came back.
    assert second_page["next_after"] == 2

    third_page = client.get(
        "/api/v1/events", params={"after": second_page["next_after"], "limit": 1}
    ).json()
    assert third_page["items"] == []
    assert third_page["next_after"] is None


@pytest.mark.integration
def test_event_feed_omits_payloads(client: TestClient) -> None:
    _create(client, "no payload here")

    item = client.get("/api/v1/events").json()["items"][0]

    assert "payload" not in item
    assert "attributes" not in item
    assert item["actor"] == "claude"


# -- /events/stream (ADR-0023) ------------------------------------------------


@pytest.mark.integration
def test_stream_rejects_beyond_the_concurrency_cap(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(events_router, "_MAX_CONCURRENT_STREAMS", 0)

    response = client.get("/api/v1/events/stream")

    assert response.status_code == 409
    assert response.headers["content-type"].startswith("application/problem+json")
    assert "too many concurrent event streams" in response.json()["detail"]
