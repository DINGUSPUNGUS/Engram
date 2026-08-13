"""/stats, /settings, /admin/rebuild — space health and configuration over HTTP
(ADR-0021 §2). Assert these forward existing computations rather than invent new
ones: the same rebuild count ``engram rebuild`` reports, the same drift check
``engram status`` reports."""

import uuid
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from engram_api.config import EngramSettings
from engram_api.main import create_app
from engram_core.application.commands.drafts import CreateMemoryDraft, to_dict

ACTOR_HEADERS = {"X-Engram-Actor": "claude"}


def _draft() -> dict[str, object]:
    """A well-formed create intent — the same shape test_proposal_review_api.py
    uses — so opening a proposal here appends a real ProposalOpened event."""
    return to_dict(
        CreateMemoryDraft(
            memory_id=uuid.uuid4(),
            kind="preference",
            slug="prefers-dark-mode",
            title="Prefers dark mode",
            content="",
            attributes={"polarity": "likes", "strength": 0.5, "context": "UI"},
            attributes_schema_version=1,
            tags=(),
            confidence=0.8,
            lifetime_policy="permanent",
            lifetime_until=None,
            visibility="private",
        )
    )


@pytest.fixture
def client(tmp_path: Path) -> Iterator[TestClient]:
    app = create_app(EngramSettings(data_dir=tmp_path, env="test"))
    with TestClient(app, headers=ACTOR_HEADERS, raise_server_exceptions=False) as test_client:
        yield test_client


@pytest.mark.integration
def test_stats_reflects_writes(client: TestClient) -> None:
    empty = client.get("/api/v1/stats").json()
    assert empty["event_count"] == 0
    assert empty["memory_count"] == 0
    assert empty["proposal_count"] == 0
    assert empty["drifted"] is False

    client.post(
        "/api/v1/memories",
        json={
            "kind": "fact",
            "title": "engram uses event sourcing",
            "attributes": {"statement": "x"},
        },
    )
    opened = client.post(
        "/api/v1/proposals",
        json={"title": "a draft proposal", "proposed_events": [_draft()]},
    )
    assert opened.status_code == 201, opened.text

    after = client.get("/api/v1/stats").json()
    assert after["event_count"] == 2  # MemoryCreated + ProposalOpened
    assert after["memory_count"] == 1
    assert after["proposal_count"] == 1
    assert after["head_global_seq"] == 2
    assert {p["name"] for p in after["projections"]} >= {"state", "search"}


@pytest.mark.integration
def test_settings_reports_existing_configuration(client: TestClient, tmp_path: Path) -> None:
    response = client.get("/api/v1/settings")

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["data_dir"] == str(tmp_path)
    assert "proposal_submission" in body["assistant_capabilities"]
    assert isinstance(body["export_repo_initialized"], bool)


@pytest.mark.integration
def test_rebuild_replays_the_log(client: TestClient) -> None:
    client.post(
        "/api/v1/memories",
        json={"kind": "fact", "title": "rebuildable", "attributes": {"statement": "x"}},
    )

    response = client.post("/admin/rebuild")

    assert response.status_code == 202, response.text
    assert response.json()["events_replayed"] == 1


@pytest.mark.integration
def test_rebuild_is_idempotent(client: TestClient) -> None:
    """Rebuilding twice in a row must not duplicate or lose anything — the M2
    disposability invariant holds without a live database to compare against
    over HTTP, so this is the half of it a black-box client can assert."""
    created = client.post(
        "/api/v1/memories",
        json={"kind": "fact", "title": "before rebuild", "attributes": {"statement": "x"}},
    ).json()

    client.post("/admin/rebuild")
    client.post("/admin/rebuild")

    assert client.get(f"/api/v1/memories/{created['id']}").status_code == 200
    assert client.get("/api/v1/stats").json()["memory_count"] == 1
