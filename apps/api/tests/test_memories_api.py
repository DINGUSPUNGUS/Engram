"""The memory surface over HTTP: CRUD, the justification spine, timeline, time
travel, and single-memory undo (ADR-0021). These prove the router adds no
behavior of its own — every guard is the aggregate's, surfaced as a problem
response (ADR-0007)."""

import uuid
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from engram_api.config import EngramSettings
from engram_api.main import create_app

ACTOR_HEADERS = {"X-Engram-Actor": "claude", "X-Engram-Session": "sess-1"}


@pytest.fixture
def client(tmp_path: Path) -> Iterator[TestClient]:
    app = create_app(EngramSettings(data_dir=tmp_path, env="test"))
    with TestClient(app, headers=ACTOR_HEADERS, raise_server_exceptions=False) as test_client:
        yield test_client


def create_memory(client: TestClient, **overrides: object) -> dict[str, object]:
    body = {
        "kind": "preference",
        "title": "Prefers dark mode",
        "content": "User said they prefer dark mode.",
        "attributes": {"polarity": "likes", "strength": 0.8, "context": "UI"},
        "tags": ["ui"],
        "visibility": "private",
        **overrides,
    }
    response = client.post("/api/v1/memories", json=body)
    assert response.status_code == 201, response.text
    result: dict[str, object] = response.json()
    return result


@pytest.mark.integration
def test_create_get_list(client: TestClient) -> None:
    created = create_memory(client)
    memory_id = created["id"]

    fetched = client.get(f"/api/v1/memories/{memory_id}").json()
    assert fetched["title"] == "Prefers dark mode"
    assert fetched["version"] == 1
    assert fetched["created_at"]  # provenance-derived, not client-supplied

    listing = client.get("/api/v1/memories").json()
    assert any(item["id"] == memory_id for item in listing["items"])


@pytest.mark.integration
def test_edit_requires_current_expected_version(client: TestClient) -> None:
    memory_id = create_memory(client)["id"]

    stale = client.patch(
        f"/api/v1/memories/{memory_id}",
        json={"expected_version": 999, "title": "New title"},
    )
    assert stale.status_code == 409

    fresh = client.patch(
        f"/api/v1/memories/{memory_id}",
        json={"expected_version": 1, "title": "New title"},
    )
    assert fresh.status_code == 200, fresh.text
    assert fresh.json()["title"] == "New title"
    assert fresh.json()["version"] == 2


@pytest.mark.integration
def test_confirm_raises_confidence_and_resets_staleness(client: TestClient) -> None:
    memory_id = create_memory(client)["id"]
    before = client.get(f"/api/v1/memories/{memory_id}").json()["confidence"]

    confirmed = client.post(f"/api/v1/memories/{memory_id}/confirm", json={"note": "still true"})

    assert confirmed.status_code == 200, confirmed.text
    assert confirmed.json()["confidence"] >= before
    assert confirmed.json()["last_confirmed_at"] is not None


@pytest.mark.integration
def test_evidence_and_importance_and_visibility_and_lifetime(client: TestClient) -> None:
    memory_id = create_memory(client)["id"]

    evidence = client.post(
        f"/api/v1/memories/{memory_id}/evidence",
        json={"evidence_type": "quote", "value": '"I like dark mode"'},
    )
    assert evidence.status_code == 201, evidence.text
    assert len(evidence.json()["evidence"]) == 1

    importance = client.patch(f"/api/v1/memories/{memory_id}/importance", json={"pinned": True})
    assert importance.status_code == 200
    assert importance.json()["pinned"] is True

    visibility = client.patch(
        f"/api/v1/memories/{memory_id}/visibility", json={"visibility": "shared"}
    )
    assert visibility.status_code == 200
    assert visibility.json()["visibility"] == "shared"

    lifetime = client.patch(
        f"/api/v1/memories/{memory_id}/lifetime", json={"lifetime_policy": "permanent"}
    )
    assert lifetime.status_code == 200
    assert lifetime.json()["lifetime_policy"] == "permanent"


@pytest.mark.integration
def test_contradict_unknown_target_is_404(client: TestClient) -> None:
    memory_id = create_memory(client)["id"]

    response = client.post(
        f"/api/v1/memories/{memory_id}/contradict",
        json={"contradicting_id": str(uuid.uuid4()), "note": "conflicts"},
    )

    assert response.status_code == 404


@pytest.mark.integration
def test_timeline_lists_events_oldest_first(client: TestClient) -> None:
    memory_id = create_memory(client)["id"]
    client.patch(f"/api/v1/memories/{memory_id}", json={"expected_version": 1, "title": "v2"})

    entries = client.get(f"/api/v1/memories/{memory_id}/timeline").json()["entries"]

    assert [e["event_type"] for e in entries] == ["MemoryCreated", "MemoryEdited"]
    assert [e["stream_seq"] for e in entries] == [1, 2]
    assert all(e["provenance"]["actor"] == "claude" for e in entries)
    assert all(e["provenance"]["session_id"] == "sess-1" for e in entries)


@pytest.mark.integration
def test_time_travel_reconstructs_earlier_version(client: TestClient) -> None:
    memory_id = create_memory(client)["id"]
    client.patch(f"/api/v1/memories/{memory_id}", json={"expected_version": 1, "title": "v2"})

    at_v1 = client.get(f"/api/v1/memories/{memory_id}/at", params={"version": 1})
    assert at_v1.status_code == 200, at_v1.text
    assert at_v1.json()["title"] == "Prefers dark mode"

    current = client.get(f"/api/v1/memories/{memory_id}").json()
    assert current["title"] == "v2"


@pytest.mark.integration
def test_time_travel_requires_exactly_one_selector(client: TestClient) -> None:
    memory_id = create_memory(client)["id"]

    neither = client.get(f"/api/v1/memories/{memory_id}/at")
    both = client.get(
        f"/api/v1/memories/{memory_id}/at", params={"version": 1, "at": "2020-01-01T00:00:00Z"}
    )

    assert neither.status_code == 422
    assert both.status_code == 422


@pytest.mark.integration
def test_undo_compensates_the_last_change(client: TestClient) -> None:
    memory_id = create_memory(client)["id"]
    client.patch(f"/api/v1/memories/{memory_id}", json={"expected_version": 1, "title": "v2"})

    undone = client.post(f"/api/v1/memories/{memory_id}/undo")

    assert undone.status_code == 200, undone.text
    assert undone.json()["memory"]["title"] == "Prefers dark mode"
    assert undone.json()["compensating_event_id"]

    entries = client.get(f"/api/v1/memories/{memory_id}/timeline").json()["entries"]
    assert [e["event_type"] for e in entries] == ["MemoryCreated", "MemoryEdited", "MemoryEdited"]


@pytest.mark.integration
def test_undo_of_delete_is_refused_no_compensator(client: TestClient) -> None:
    """Delete has no defined inverse (matches proposal undo's own refusal for
    the same event type) — undo must not silently fabricate a restore."""
    memory_id = create_memory(client)["id"]
    client.delete(f"/api/v1/memories/{memory_id}")

    response = client.post(f"/api/v1/memories/{memory_id}/undo")

    assert response.status_code == 409
    assert "no compensator exists" in response.json()["detail"]


@pytest.mark.integration
def test_undo_unknown_memory_is_404(client: TestClient) -> None:
    response = client.post(f"/api/v1/memories/{uuid.uuid4()}/undo")
    assert response.status_code == 404


@pytest.mark.integration
def test_delete_then_get_is_404(client: TestClient) -> None:
    memory_id = create_memory(client)["id"]

    deleted = client.delete(f"/api/v1/memories/{memory_id}", params={"reason": "duplicate"})
    assert deleted.status_code == 204

    assert client.get(f"/api/v1/memories/{memory_id}").status_code == 404
