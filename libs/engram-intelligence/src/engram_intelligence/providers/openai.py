"""OpenAI provider. The ``openai`` SDK will be imported here and only here, added
as an optional extra when implemented (roadmap phase 8)."""

from engram_intelligence.provider import LLMRequest, LLMResponse


class OpenAIProvider:
    """Adapter over the OpenAI Responses/Chat API."""

    def __init__(self, model: str, api_key: str | None = None) -> None:
        self._model = model
        self._api_key = api_key

    @property
    def name(self) -> str:
        return "openai"

    @property
    def supports_json_output(self) -> bool:
        return True

    def complete(self, request: LLMRequest) -> LLMResponse:
        raise NotImplementedError
