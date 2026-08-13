"""API contract tests: the shell works end-to-end. M7a closed the last
architecture-phase stub (``apps/api/src/engram_api`` has no remaining
``NotImplementedError``); ``errors.py`` still maps one to a well-formed 501
problem for whatever the next milestone adds, and that mapping is unit-tested
in isolation rather than against a router that no longer stubs anything."""

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
def test_not_implemented_still_surfaces_as_problem_501() -> None:
    """The mapping itself, isolated from any specific route (M7a left none
    stubbed): a future ``NotImplementedError`` is a well-formed problem, never
    a raw 500."""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient as _TestClient

    from engram_api.errors import register_error_handlers

    app = FastAPI()
    register_error_handlers(app)

    @app.get("/not-yet")
    async def _not_yet() -> None:
        raise NotImplementedError

    response = _TestClient(app, raise_server_exceptions=False).get("/not-yet")

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
