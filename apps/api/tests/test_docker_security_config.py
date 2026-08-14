"""P1 regression: Docker's published ports must stay loopback-scoped by
default (docs/security.md: "Binds 127.0.0.1 by default... changing the bind
host is an explicit, documented opt-in").

Each container's own process necessarily binds ``0.0.0.0`` internally — a
Docker networking requirement, not a security choice, since a container-
internal ``127.0.0.1`` bind is unreachable via ``-p``/compose from anywhere.
The actual loopback control point is the host-side publish mapping in
``docker-compose.yml``; these are plain text checks, not full YAML/Dockerfile
parses, deliberately — they exist to catch the mapping or the bind silently
regressing to network-wide exposure, not to validate Docker syntax.
"""

from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[3]


@pytest.mark.unit
def test_compose_publishes_ports_loopback_only() -> None:
    compose = (_REPO_ROOT / "docker-compose.yml").read_text(encoding="utf-8")
    for port in ("8000", "3000"):
        mapping = f'"127.0.0.1:{port}:{port}"'
        assert mapping in compose, (
            f"docker-compose.yml must publish port {port} as {mapping} — a bare"
            f' "{port}:{port}" mapping exposes it on every host interface by'
            " default, contradicting docs/security.md."
        )


@pytest.mark.unit
def test_api_dockerfile_bind_is_env_driven_not_hardcoded() -> None:
    dockerfile = (_REPO_ROOT / "docker" / "api.Dockerfile").read_text(encoding="utf-8")
    assert '"--host", "0.0.0.0"' not in dockerfile, (
        "the API's bind must come from $ENGRAM_API_HOST (operations.md), not a"
        " CMD argument that hardcodes it and ignores the setting entirely"
    )
    assert "$ENGRAM_API_HOST" in dockerfile
    assert "$ENGRAM_API_PORT" in dockerfile
