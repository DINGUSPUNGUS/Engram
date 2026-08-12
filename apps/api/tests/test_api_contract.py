"""API contract tests: the shell works end-to-end, and endpoints still awaiting
implementation surface as well-formed 501 problems, never as raw 500s."""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from engram_api.config import EngramSettings
from engram_api.main import create_app


@pytest.fixture
def client(tmp_path: Path) -> TestClient:
    """Each app gets its own data directory.

    ``create_app`` now builds a runtime, which migrates a database into
    ``data_dir`` — defaulting that to ``~/.engram`` would let the suite write to
    the developer's real space.
    """
    app = create_app(EngramSettings(data_dir=tmp_path, env="test"))
    return TestClient(app, raise_server_exceptions=False)


@pytest.mark.unit
def test_healthz(client: TestClient) -> None:
    response = client.get("/healthz")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


@pytest.mark.unit
def test_version(client: TestClient) -> None:
    response = client.get("/version")
    assert response.status_code == 200
    assert "version" in response.json()


@pytest.mark.unit
@pytest.mark.parametrize(
    "method,path",
    [
        ("GET", "/api/v1/memories"),
        ("GET", "/api/v1/search?q=x"),
        ("GET", "/api/v1/events"),
        ("POST", "/admin/rebuild"),
    ],
)
def test_stub_endpoints_return_problem_501(client: TestClient, method: str, path: str) -> None:
    response = client.request(method, path)
    assert response.status_code == 501
    assert response.headers["content-type"].startswith("application/problem+json")
    body = response.json()
    assert body["status"] == 501
    assert body["title"] == "Not implemented"


@pytest.mark.unit
def test_request_id_is_echoed(client: TestClient) -> None:
    response = client.get("/healthz", headers={"X-Request-Id": "test-123"})
    assert response.headers["X-Request-Id"] == "test-123"


@pytest.mark.unit
def test_request_id_is_minted_when_absent(client: TestClient) -> None:
    response = client.get("/healthz")
    assert response.headers["X-Request-Id"]


@pytest.mark.unit
def test_openapi_schema_renders(client: TestClient) -> None:
    response = client.get("/openapi.json")
    assert response.status_code == 200
    paths = response.json()["paths"]
    assert "/api/v1/memories" in paths
    assert "/api/v1/memories/{memory_id}/timeline" in paths
