"""ChatGPT adapter: OpenAI function-calling wire shapes ⇄ canonical tools.

Definitions go out as ``{"type": "function", "function": {...}}``; calls come in
as OpenAI tool-call objects (arguments as a JSON *string*); results go back as
``role: "tool"`` messages. Nothing else — no decisions live here (ADR-0020).
"""

import json
from collections.abc import Mapping
from typing import Any

from engram_assistants.adapters._base import execute
from engram_assistants.contract import AdapterDescriptor, AssistantContext, Capability
from engram_assistants.gateway import AssistantGateway
from engram_assistants.tools import TOOLS, parse_json_arguments
from engram_core.domain.errors import ValidationError

ADAPTER_VERSION = "1.0.0"

_DEFAULT_CAPABILITIES = frozenset(
    {
        Capability.RETRIEVAL,
        Capability.PROPOSAL_SUBMISSION,
        Capability.TIMELINE,
        Capability.TOOL_CALLING,
        Capability.STREAMING,
    }
)


class ChatGPTAdapter:
    """Stateless; one instance serves every conversation."""

    def __init__(
        self,
        gateway: AssistantGateway,
        *,
        capabilities: frozenset[Capability] = _DEFAULT_CAPABILITIES,
    ) -> None:
        self._gateway = gateway
        self._descriptor = AdapterDescriptor(
            name="chatgpt",
            version=ADAPTER_VERSION,
            provider="openai",
            capabilities=capabilities,
        )

    @property
    def descriptor(self) -> AdapterDescriptor:
        return self._descriptor

    def tool_definitions(self) -> list[dict[str, object]]:
        return [
            {
                "type": "function",
                "function": {
                    "name": spec.name,
                    "description": spec.description,
                    "parameters": spec.parameters,
                },
            }
            for spec in TOOLS
        ]

    def handle_tool_call(
        self, call: Mapping[str, object], context: AssistantContext
    ) -> dict[str, object]:
        """One OpenAI tool call in, one ``role: "tool"`` message out."""
        function = call.get("function")
        if not isinstance(function, Mapping) or "name" not in function:
            raise ValidationError("malformed OpenAI tool call: missing function.name")
        arguments = parse_json_arguments(function.get("arguments") or "{}")
        payload, _is_error = execute(
            self._gateway, self._descriptor, context, str(function["name"]), arguments
        )
        result: dict[str, Any] = {
            "role": "tool",
            "tool_call_id": str(call.get("id") or ""),
            "content": json.dumps(payload, sort_keys=True),
        }
        return result
