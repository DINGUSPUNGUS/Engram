"""The review workflow over HTTP: open → approve → merge → undo.

These tests exist to prove the REST surface cannot weaken the domain's guarantees.
Every illegal transition must be refused by the aggregate and surface as a problem
response — the API is a shell (ADR-0007), so it has no power to skip a step.
"""

import uuid
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from engram_api.config import EngramSettings
from engram_api.main import create_app
from engram_core.application.commands.drafts import CreateMemoryDraft, to_dict

ACTOR_HEADERS = {"X-Engram-Actor": "claude", "X-Engram-Session": "sess-1"}


@pytest.fixture
def client(tmp_path: Path) -> Iterator[TestClient]:
    app = create_app(EngramSettings(data_dir=tmp_path, env="test"))
    with TestClient(app, headers=ACTOR_HEADERS, raise_server_exceptions=False) as test_client:
        yield test_client


def make_draft(memory_id: uuid.UUID | None = None) -> dict[str, object]:
    """A well-formed create intent, serialized by the domain's own writer."""
    return to_dict(
        CreateMemoryDraft(
            memory_id=memory_id or uuid.uuid4(),
            kind="preference",
            slug="prefers-dark-mode",
            title="Prefers dark mode",
            content="User said they prefer dark mode.",
            attributes={"polarity": "likes", "strength": 0.8, "context": "UI"},
            attributes_schema_version=1,
            tags=("ui",),
            confidence=0.8,
            lifetime_policy="permanent",
            lifetime_until=None,
            visibility="private",
        )
    )


def open_proposal(client: TestClient) -> str:
    response = client.post(
        "/api/v1/proposals",
        json={
            "title": "Remember UI preference",
            "description": "extracted from chat",
            "proposed_events": [make_draft()],
        },
    )
    assert response.status_code == 201, response.text
    return str(response.json()["id"])


@pytest.mark.integration
def test_open_records_drafts_and_opening_assistant(client: TestClient) -> None:
    proposal_id = open_proposal(client)

    detail = client.get(f"/api/v1/proposals/{proposal_id}").json()
    assert detail["status"] == "pending"
    assert len(detail["drafts"]) == 1
    assert detail["merged_event_ids"] == []

    row = client.get("/api/v1/proposals").json()["items"][0]
    assert row["opened_by"] == "claude"
    assert row["draft_count"] == 1


@pytest.mark.integration
def test_full_lifecycle_open_approve_merge_undo(client: TestClient) -> None:
    proposal_id = open_proposal(client)

    assert (
        client.post(
            f"/api/v1/proposals/{proposal_id}/approve", json={"note": "looks right"}
        ).json()["status"]
        == "approved"
    )

    merged = client.post(f"/api/v1/proposals/{proposal_id}/merge")
    assert merged.status_code == 200, merged.text
    appended = merged.json()["appended_event_ids"]
    assert len(appended) == 1
    assert merged.json()["proposal"]["status"] == "merged"

    # Merge provenance is recorded on the proposal, not derived by the client.
    assert client.get(f"/api/v1/proposals/{proposal_id}").json()["merged_event_ids"] == appended

    undone = client.post(f"/api/v1/proposals/{proposal_id}/undo", json={"note": "mistake"})
    assert undone.status_code == 200, undone.text
    assert undone.json()["compensating_event_ids"]
    assert undone.json()["proposal"]["status"] == "undone"


@pytest.mark.integration
def test_merge_without_approval_is_refused(client: TestClient) -> None:
    """The UI cannot skip review: merging a pending proposal is a 409."""
    proposal_id = open_proposal(client)

    response = client.post(f"/api/v1/proposals/{proposal_id}/merge")

    assert response.status_code == 409
    assert response.headers["content-type"].startswith("application/problem+json")
    assert "only approved proposals merge" in response.json()["detail"]


@pytest.mark.integration
def test_undo_before_merge_is_refused(client: TestClient) -> None:
    """Compensation only applies to something that happened (ADR-0018 §3)."""
    proposal_id = open_proposal(client)
    client.post(f"/api/v1/proposals/{proposal_id}/approve", json={"note": None})

    response = client.post(f"/api/v1/proposals/{proposal_id}/undo", json={"note": None})

    assert response.status_code == 409
    assert "only merged proposals undo" in response.json()["detail"]


@pytest.mark.integration
def test_rejected_proposal_cannot_be_merged(client: TestClient) -> None:
    proposal_id = open_proposal(client)
    client.post(f"/api/v1/proposals/{proposal_id}/reject", json={"note": "not useful"})

    assert client.get(f"/api/v1/proposals/{proposal_id}").json()["status"] == "rejected"
    assert client.post(f"/api/v1/proposals/{proposal_id}/merge").status_code == 409


@pytest.mark.integration
def test_double_approval_is_refused(client: TestClient) -> None:
    proposal_id = open_proposal(client)
    client.post(f"/api/v1/proposals/{proposal_id}/approve", json={"note": None})

    assert (
        client.post(f"/api/v1/proposals/{proposal_id}/approve", json={"note": None}).status_code
        == 409
    )


@pytest.mark.integration
def test_timeline_exposes_lifecycle_and_provenance(client: TestClient) -> None:
    """What the observatory reads: the lifecycle, and who caused each step."""
    proposal_id = open_proposal(client)
    client.post(f"/api/v1/proposals/{proposal_id}/approve", json={"note": None})
    client.post(f"/api/v1/proposals/{proposal_id}/merge")

    entries = client.get(f"/api/v1/proposals/{proposal_id}/timeline").json()["entries"]

    assert [entry["event_type"] for entry in entries] == [
        "ProposalOpened",
        "ProposalApproved",
        "ProposalMerged",
    ]
    assert all(entry["provenance"]["actor"] == "claude" for entry in entries)
    assert all(entry["provenance"]["session_id"] == "sess-1" for entry in entries)
    assert [entry["stream_seq"] for entry in entries] == [1, 2, 3]


@pytest.mark.integration
def test_unknown_proposal_is_404(client: TestClient) -> None:
    missing = uuid.uuid4()

    assert client.get(f"/api/v1/proposals/{missing}").status_code == 404
    assert client.get(f"/api/v1/proposals/{missing}/timeline").status_code == 404


@pytest.mark.integration
def test_malformed_draft_is_rejected_by_the_service(client: TestClient) -> None:
    """Draft validation belongs to the domain, not to the router."""
    response = client.post(
        "/api/v1/proposals",
        json={"title": "Bad", "description": "", "proposed_events": [{"op": "nonsense"}]},
    )

    assert response.status_code == 422
    assert response.headers["content-type"].startswith("application/problem+json")
