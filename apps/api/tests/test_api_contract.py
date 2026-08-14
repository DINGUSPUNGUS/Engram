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


# PRE-M10 GATE finding (API/dashboard P1): FastAPI's own request-parsing
# failures (missing/out-of-range params, an unparseable path param, a
# malformed body) and Starlette's own routing failures (unmatched path,
# unsupported method) both run *before* any router body executes, so neither
# ever reached ``handle_engram_error`` — every operation's OpenAPI schema
# still promises its 4XX response is ``application/problem+json``
# (``PROBLEM_RESPONSES``), but FastAPI's own default rendered a plain
# ``{"detail": [...]}`` instead. Confirmed live pre-fix: none of the six
# cases below returned ``application/problem+json``, and the dashboard's own
# ``Problem.detail`` type (``string | null``) can't represent the list of
# objects FastAPI's default shape hands back for a validation failure.
@pytest.mark.unit
@pytest.mark.parametrize(
    ("method", "path", "kwargs", "expected_status"),
    [
        ("GET", "/api/v1/search", {}, 422),  # missing required query param
        ("GET", "/api/v1/memories", {"params": {"limit": 99999}}, 422),  # out of range
        ("GET", "/api/v1/memories/not-a-uuid", {}, 422),  # unparseable path param
        ("POST", "/api/v1/memories", {"json": {"title": "x"}}, 422),  # missing body field
        ("GET", "/api/v1/nope-such-route", {}, 404),  # unmatched route
        ("PUT", "/api/v1/memories", {}, 405),  # unsupported method on a real route
    ],
)
def test_native_request_errors_are_still_problem_json(
    client: TestClient, method: str, path: str, kwargs: dict[str, object], expected_status: int
) -> None:
    response = client.request(method, path, **kwargs)

    assert response.status_code == expected_status
    assert response.headers["content-type"].startswith("application/problem+json")
    body = response.json()
    assert isinstance(body["detail"], str)  # never the raw list FastAPI's default hands back
    assert body["status"] == expected_status
    assert body["instance"] == path
