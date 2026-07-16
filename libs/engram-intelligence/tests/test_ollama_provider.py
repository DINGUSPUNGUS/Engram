"""OllamaProvider: request shape, determinism pins, retry policy, error mapping.
The provider calls ``httpx.post`` through the shared module object, so patching
``httpx.post`` intercepts every request — these tests never need a server."""

from typing import Any

import httpx
import pytest
from engram_intelligence.providers import ollama as ollama_module
from engram_intelligence.providers.ollama import OllamaProvider

from engram_core.domain.errors import StorageError


def _request(json_output: bool = True) -> Any:
    from engram_intelligence.provider import LLMRequest

    return LLMRequest(
        prompt_name="evidence-extraction",
        prompt_version=1,
        rendered_prompt="extract",
        system="be terse",
        json_output=json_output,
    )


def _response(status: int = 200, body: dict[str, Any] | None = None) -> httpx.Response:
    return httpx.Response(
        status_code=status,
        json=body
        if body is not None
        else {
            "model": "llama3.2:1b",
            "message": {"role": "assistant", "content": "[]"},
            "prompt_eval_count": 10,
            "eval_count": 2,
        },
        request=httpx.Request("POST", "http://127.0.0.1:11434/api/chat"),
    )


@pytest.mark.unit
def test_request_carries_the_determinism_pins(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[dict[str, Any]] = []

    def fake_post(url: str, *, json: dict[str, Any], timeout: float) -> httpx.Response:
        seen.append({"url": url, "body": json, "timeout": timeout})
        return _response()

    monkeypatch.setattr(httpx, "post", fake_post)
    provider = OllamaProvider("llama3.2:1b", seed=7, timeout_seconds=30.0)
    result = provider.complete(_request())

    body = seen[0]["body"]
    assert seen[0]["url"].endswith("/api/chat")
    assert seen[0]["timeout"] == 30.0
    assert body["model"] == "llama3.2:1b"
    assert body["options"] == {"temperature": 0.0, "seed": 7, "num_predict": 2048}
    assert body["format"] == "json"
    assert [m["role"] for m in body["messages"]] == ["system", "user"]
    assert result.text == "[]"
    assert result.usage.input_tokens == 10 and result.usage.output_tokens == 2
    assert result.model_id == "llama3.2:1b"  # provenance only


@pytest.mark.unit
def test_transport_errors_retry_then_surface(monkeypatch: pytest.MonkeyPatch) -> None:
    attempts: list[int] = []

    def flaky_post(url: str, *, json: dict[str, Any], timeout: float) -> httpx.Response:
        attempts.append(1)
        if len(attempts) < 2:
            raise httpx.ConnectError("refused")
        return _response()

    monkeypatch.setattr(ollama_module, "_RETRY_BACKOFF_SECONDS", 0.0)
    monkeypatch.setattr(httpx, "post", flaky_post)
    provider = OllamaProvider("m")
    assert provider.complete(_request()).text == "[]"
    assert len(attempts) == 2  # one retry, then success

    def dead_post(url: str, *, json: dict[str, Any], timeout: float) -> httpx.Response:
        raise httpx.ConnectError("refused")

    monkeypatch.setattr(httpx, "post", dead_post)
    with pytest.raises(StorageError, match="cannot reach ollama"):
        provider.complete(_request())


@pytest.mark.unit
def test_http_errors_do_not_retry_and_map_to_storage_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    attempts: list[int] = []

    def failing_post(url: str, *, json: dict[str, Any], timeout: float) -> httpx.Response:
        attempts.append(1)
        response = _response(status=404, body={"error": "model not found"})
        response.raise_for_status()  # pragma: no cover - raises below via provider
        return response

    monkeypatch.setattr(httpx, "post", failing_post)
    with pytest.raises(StorageError, match="HTTP 404"):
        OllamaProvider("missing-model").complete(_request())
    assert len(attempts) == 1  # deterministic failures never retry


@pytest.mark.unit
def test_malformed_bodies_are_translated_never_leaked(monkeypatch: pytest.MonkeyPatch) -> None:
    def weird_post(url: str, *, json: dict[str, Any], timeout: float) -> httpx.Response:
        return _response(body={"model": "m", "message": "not an object"})

    monkeypatch.setattr(httpx, "post", weird_post)
    with pytest.raises(StorageError, match="unexpected body"):
        OllamaProvider("m").complete(_request())
