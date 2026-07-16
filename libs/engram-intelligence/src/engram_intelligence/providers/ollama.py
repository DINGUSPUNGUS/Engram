"""Ollama provider — the local-first reference default (ADR-0012).

Every pipeline stage must be fully functional against a local model with zero cloud
dependencies. Plain HTTP to the Ollama API; no SDK needed. Determinism is pinned as
far as the backend allows: a fixed ``seed`` and ``temperature`` travel with every
request (ADR-0019 §3); both are recorded in pipeline provenance.

Retry policy lives HERE and only here (the provider boundary): transient transport
failures are retried a bounded number of times; HTTP errors and malformed bodies
are not (they are deterministic and would fail identically).
"""

import json
import time

import httpx

from engram_core.domain.errors import StorageError
from engram_intelligence.provider import LLMRequest, LLMResponse, LLMUsage

_DEFAULT_BASE_URL = "http://127.0.0.1:11434"


def _count(value: object) -> int:
    return value if isinstance(value, int) else 0


_DEFAULT_TIMEOUT_SECONDS = 120.0
_DEFAULT_SEED = 42
_TRANSPORT_RETRIES = 2
_RETRY_BACKOFF_SECONDS = 0.5


class OllamaProvider:
    """Talks to a local Ollama server via ``/api/chat``."""

    def __init__(
        self,
        model: str,
        base_url: str = _DEFAULT_BASE_URL,
        *,
        timeout_seconds: float = _DEFAULT_TIMEOUT_SECONDS,
        seed: int = _DEFAULT_SEED,
    ) -> None:
        self._model = model
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout_seconds
        self._seed = seed

    @property
    def name(self) -> str:
        return "ollama"

    @property
    def supports_json_output(self) -> bool:
        return True  # Ollama's format=json mode

    @property
    def seed(self) -> int:
        """The pinned sampling seed, recorded in pipeline provenance."""
        return self._seed

    def complete(self, request: LLMRequest) -> LLMResponse:
        messages: list[dict[str, str]] = []
        if request.system is not None:
            messages.append({"role": "system", "content": request.system})
        messages.append({"role": "user", "content": request.rendered_prompt})
        body: dict[str, object] = {
            "model": self._model,
            "messages": messages,
            "stream": False,
            "options": {
                "temperature": request.temperature,
                "seed": self._seed,
                "num_predict": request.max_output_tokens,
            },
        }
        if request.json_output:
            body["format"] = "json"

        started = time.monotonic()
        data = self._post(body, context=f"prompt {request.prompt_name}@{request.prompt_version}")
        latency_ms = int((time.monotonic() - started) * 1000)

        message = data.get("message")
        if not isinstance(message, dict) or not isinstance(message.get("content"), str):
            raise StorageError(f"ollama returned an unexpected body for {request.prompt_name}")
        return LLMResponse(
            text=message["content"],
            usage=LLMUsage(
                input_tokens=_count(data.get("prompt_eval_count")),
                output_tokens=_count(data.get("eval_count")),
            ),
            model_id=str(data.get("model") or self._model),
            latency_ms=latency_ms,
        )

    def _post(self, body: dict[str, object], *, context: str) -> dict[str, object]:
        last_error: httpx.TransportError | None = None
        for attempt in range(_TRANSPORT_RETRIES + 1):
            if attempt:
                time.sleep(_RETRY_BACKOFF_SECONDS * attempt)
            try:
                response = httpx.post(
                    f"{self._base_url}/api/chat", json=body, timeout=self._timeout
                )
                response.raise_for_status()
                payload = response.json()
                if not isinstance(payload, dict):
                    raise StorageError(f"ollama returned non-object JSON for {context}")
                return payload
            except httpx.TransportError as exc:
                last_error = exc  # connection refused / timeout — worth retrying
            except httpx.HTTPStatusError as exc:
                raise StorageError(
                    f"ollama rejected {context}: HTTP {exc.response.status_code}"
                    f" — {exc.response.text[:200]}"
                ) from exc
            except json.JSONDecodeError as exc:
                raise StorageError(f"ollama returned invalid JSON for {context}") from exc
        raise StorageError(
            f"cannot reach ollama at {self._base_url} for {context}"
            f" after {_TRANSPORT_RETRIES + 1} attempts: {last_error}"
        ) from last_error
