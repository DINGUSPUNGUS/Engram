"""Anthropic Claude provider. The ``anthropic`` SDK will be imported here and only
here, added as an optional extra when implemented (milestone M5)."""

from engram_intelligence.provider import LLMRequest, LLMResponse


class ClaudeProvider:
    """Adapter over the Anthropic Messages API."""

    def __init__(self, model: str, api_key: str | None = None) -> None:
        self._model = model
        self._api_key = api_key

    @property
    def name(self) -> str:
        return "claude"

    @property
    def supports_json_output(self) -> bool:
        return True

    def complete(self, request: LLMRequest) -> LLMResponse:
        raise NotImplementedError
