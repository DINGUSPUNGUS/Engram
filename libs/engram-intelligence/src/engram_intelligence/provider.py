"""The LLM provider port (ADR-0012).

Deliberately minimal: request in, response out, capability flags. The ``model_id`` on
responses is recorded for provenance ONLY — no code in engram may branch on it. If a
stage needs a capability, it asks the flags, never the vendor name.
"""

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True, slots=True)
class LLMRequest:
    """One completion request. Carries the prompt's identity for the audit trail."""

    prompt_name: str
    prompt_version: int
    rendered_prompt: str
    system: str | None = None
    temperature: float = 0.0
    max_output_tokens: int = 2048
    json_output: bool = False


@dataclass(frozen=True, slots=True)
class LLMUsage:
    input_tokens: int
    output_tokens: int


@dataclass(frozen=True, slots=True)
class LLMResponse:
    """A completion. ``model_id`` is opaque provenance — never branch on it."""

    text: str
    usage: LLMUsage
    model_id: str
    latency_ms: int


class LLMProvider(Protocol):
    """What every model backend must offer. Implementations live in ``providers/``;
    vendor SDKs are confined there (ADR-0012)."""

    @property
    def name(self) -> str:
        """Stable provider name for configuration and provenance ("ollama", …)."""
        ...

    @property
    def supports_json_output(self) -> bool:
        """Whether ``json_output=True`` requests are honored natively."""
        ...

    def complete(self, request: LLMRequest) -> LLMResponse:
        """Execute one completion.

        Raises:
            StorageError: transport/provider failure (translated, never leaked SDKs).
        """
        ...


class FakeProvider:
    """Deterministic provider for tests and golden-set runs of non-LLM concerns.

    Returns canned responses keyed by prompt name; unknown prompts get the default.
    """

    def __init__(self, responses: dict[str, str] | None = None, default: str = "") -> None:
        self._responses = dict(responses or {})
        self._default = default

    @property
    def name(self) -> str:
        return "fake"

    @property
    def supports_json_output(self) -> bool:
        return True

    def complete(self, request: LLMRequest) -> LLMResponse:
        text = self._responses.get(request.prompt_name, self._default)
        return LLMResponse(
            text=text,
            usage=LLMUsage(input_tokens=0, output_tokens=0),
            model_id="fake",
            latency_ms=0,
        )
