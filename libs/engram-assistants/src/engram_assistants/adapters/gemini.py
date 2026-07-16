"""Gemini adapter: Google function-declaration wire shapes ⇄ canonical tools.

Definitions go out as ``functionDeclarations``; calls come in as ``functionCall``
parts (args already a JSON object); results go back as ``functionResponse`` parts.
Nothing else lives here (ADR-0020).
"""

from collections.abc import Mapping

from engram_assistants.adapters._base import execute
from engram_assistants.contract import AdapterDescriptor, AssistantContext, Capability
from engram_assistants.gateway import AssistantGateway
from engram_assistants.tools import TOOLS
from engram_core.domain.errors import ValidationError

ADAPTER_VERSION = "1.0.0"

_DEFAULT_CAPABILITIES = frozenset(
    {
        Capability.RETRIEVAL,
        Capability.PROPOSAL_SUBMISSION,
        Capability.TIMELINE,
        Capability.TOOL_CALLING,
    }
)


class GeminiAdapter:
    """Stateless; one instance serves every conversation."""

    def __init__(
        self,
        gateway: AssistantGateway,
        *,
        capabilities: frozenset[Capability] = _DEFAULT_CAPABILITIES,
    ) -> None:
        self._gateway = gateway
        self._descriptor = AdapterDescriptor(
            name="gemini",
            version=ADAPTER_VERSION,
            provider="google",
            capabilities=capabilities,
        )

    @property
    def descriptor(self) -> AdapterDescriptor:
        return self._descriptor

    def tool_definitions(self) -> list[dict[str, object]]:
        return [
            {
                "functionDeclarations": [
                    {
                        "name": spec.name,
                        "description": spec.description,
                        "parameters": spec.parameters,
                    }
                    for spec in TOOLS
                ]
            }
        ]

    def handle_tool_call(
        self, call: Mapping[str, object], context: AssistantContext
    ) -> dict[str, object]:
        """One ``functionCall`` part in, one ``functionResponse`` part out."""
        function_call = call.get("functionCall")
        if not isinstance(function_call, Mapping) or "name" not in function_call:
            raise ValidationError("malformed Gemini tool call: missing functionCall.name")
        raw_args = function_call.get("args")
        arguments: Mapping[str, object] = raw_args if isinstance(raw_args, Mapping) else {}
        payload, _is_error = execute(
            self._gateway, self._descriptor, context, str(function_call["name"]), arguments
        )
        return {"functionResponse": {"name": str(function_call["name"]), "response": payload}}
