"""The adapter contract (ADR-0020): what every assistant integration must declare.

An adapter is a *translator*, not a participant: it converts one provider's wire
shapes into canonical tool calls and back. All behavior lives in the gateway;
identical semantics across providers is a construction property, not a discipline.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol

from engram_core.domain.errors import EngramError


class Capability(StrEnum):
    """What an assistant integration can do. Declared by adapters, granted and
    enforced by the gateway — an adapter cannot exceed its declaration."""

    RETRIEVAL = "retrieval"  # recall_search / recall_memory
    PROPOSAL_SUBMISSION = "proposal_submission"  # remember / proposal_status
    TIMELINE = "timeline"  # memory_timeline (explainability)
    TOOL_CALLING = "tool_calling"  # native structured tool calls
    STREAMING = "streaming"  # declared for negotiation; engram needs nothing from it


class CapabilityError(EngramError):
    """The operation needs a capability the adapter did not declare (or engram
    does not support). Adapters map this to their provider's error shape —
    degradation is a well-formed answer, never a crash."""


@dataclass(frozen=True, slots=True)
class AdapterDescriptor:
    """An adapter's immutable self-description; stamped into every trace."""

    name: str  # assistant identity, e.g. "chatgpt" — becomes the provenance actor
    version: str  # adapter version (semver string)
    provider: str  # vendor family, e.g. "openai", "anthropic", "google"
    capabilities: frozenset[Capability]

    @property
    def qualified_name(self) -> str:
        return f"{self.name}@{self.version}"


@dataclass(frozen=True, slots=True)
class AssistantContext:
    """Per-interaction identity: which conversation of which assistant is asking.
    Adapters are stateless — everything request-scoped arrives here."""

    session_id: str | None = None
    model: str | None = None


class AssistantAdapter(Protocol):
    """What every provider adapter offers. Implementations live in ``adapters/``;
    each translates exactly three things: tool definitions out, tool calls in,
    results/errors back out."""

    @property
    def descriptor(self) -> AdapterDescriptor: ...

    def tool_definitions(self) -> list[dict[str, object]]:
        """The canonical engram tools, in this provider's native schema shape."""
        ...

    def handle_tool_call(
        self, call: Mapping[str, object], context: AssistantContext
    ) -> dict[str, object]:
        """Execute one provider-shaped tool call and return the provider-shaped
        result. Errors come back as well-formed provider error results."""
        ...
