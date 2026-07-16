"""Pipeline run trace: the explanation a proposal carries forever (ADR-0019 §3).

The orchestrator owns run state (docs/intelligence.md §1), so the trace lives one
per composed pipeline and is reset at the start of every ingest. ``TracingProvider``
wraps any ``LLMProvider`` so every completion is recorded with its prompt identity,
opaque model id, token usage, and latency — the stages stay oblivious.

Everything here is explanation-only metadata: it rides ``Provenance.detail`` on the
``ProposalOpened`` envelope and is folded by nothing.
"""

from dataclasses import dataclass, field

from engram_intelligence.provider import LLMProvider, LLMRequest, LLMResponse


@dataclass(frozen=True, slots=True)
class LLMCall:
    """One completion, as provenance."""

    prompt: str  # name@version
    model_id: str
    input_tokens: int
    output_tokens: int
    latency_ms: int


@dataclass
class PipelineTrace:
    """Accumulates one run's explanation."""

    configuration: dict[str, object] = field(default_factory=dict)
    calls: list[LLMCall] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def reset(self) -> None:
        """Start a new run; configuration persists (it describes the wiring)."""
        self.calls.clear()
        self.notes.clear()

    def configure(self, **settings: object) -> None:
        """Record composition-root settings (provider, model, seed, …)."""
        self.configuration.update(settings)

    def record(self, request: LLMRequest, response: LLMResponse) -> None:
        self.calls.append(
            LLMCall(
                prompt=f"{request.prompt_name}@{request.prompt_version}",
                model_id=response.model_id,
                input_tokens=response.usage.input_tokens,
                output_tokens=response.usage.output_tokens,
                latency_ms=response.latency_ms,
            )
        )

    def note(self, stage: str, message: str) -> None:
        """Record why something was skipped/dropped — absence needs explaining too."""
        self.notes.append(f"{stage}: {message}")

    def as_metadata(self) -> dict[str, object]:
        """The JSON-safe run explanation for ``Provenance.detail``."""
        return {
            "configuration": dict(self.configuration),
            "llm_calls": [
                {
                    "prompt": call.prompt,
                    "model_id": call.model_id,
                    "input_tokens": call.input_tokens,
                    "output_tokens": call.output_tokens,
                    "latency_ms": call.latency_ms,
                }
                for call in self.calls
            ],
            "notes": list(self.notes),
        }


class TracingProvider:
    """Decorates a provider so every completion lands in the trace."""

    def __init__(self, inner: LLMProvider, trace: PipelineTrace) -> None:
        self._inner = inner
        self._trace = trace

    @property
    def name(self) -> str:
        return self._inner.name

    @property
    def supports_json_output(self) -> bool:
        return self._inner.supports_json_output

    def complete(self, request: LLMRequest) -> LLMResponse:
        response = self._inner.complete(request)
        self._trace.record(request, response)
        return response
