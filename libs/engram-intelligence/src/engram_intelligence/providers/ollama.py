"""Ollama provider — the local-first reference default (ADR-0012).

Every pipeline stage must be fully functional against a local model with zero cloud
dependencies; this adapter is therefore the one implemented *first* in M5.
Plain HTTP to the Ollama API; no SDK needed.
"""

from engram_intelligence.provider import LLMRequest, LLMResponse

_DEFAULT_BASE_URL = "http://127.0.0.1:11434"


class OllamaProvider:
    """Talks to a local Ollama server."""

    def __init__(self, model: str, base_url: str = _DEFAULT_BASE_URL) -> None:
        self._model = model
        self._base_url = base_url

    @property
    def name(self) -> str:
        return "ollama"

    @property
    def supports_json_output(self) -> bool:
        return True  # Ollama's format=json mode

    def complete(self, request: LLMRequest) -> LLMResponse:
        raise NotImplementedError
