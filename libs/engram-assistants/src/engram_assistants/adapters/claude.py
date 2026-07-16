"""Claude adapter: Anthropic tool-use wire shapes ⇄ canonical tools.

Definitions go out with ``input_schema``; calls come in as ``tool_use`` content
blocks (input already a JSON object); results go back as ``tool_result`` blocks
with ``is_error`` set on failures. Nothing else lives here (ADR-0020).
"""

import json
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
        Capability.STREAMING,
    }
)


class ClaudeAdapter:
    """Stateless; one instance serves every conversation."""

    def __init__(
        self,
        gateway: AssistantGateway,
        *,
        capabilities: frozenset[Capability] = _DEFAULT_CAPABILITIES,
    ) -> None:
        self._gateway = gateway
        self._descriptor = AdapterDescriptor(
            name="claude",
            version=ADAPTER_VERSION,
            provider="anthropic",
            capabilities=capabilities,
        )

    @property
    def descriptor(self) -> AdapterDescriptor:
        return self._descriptor

    def tool_definitions(self) -> list[dict[str, object]]:
        return [
            {
                "name": spec.name,
                "description": spec.description,
                "input_schema": spec.parameters,
            }
            for spec in TOOLS
        ]

    def handle_tool_call(
        self, call: Mapping[str, object], context: AssistantContext
    ) -> dict[str, object]:
        """One ``tool_use`` block in, one ``tool_result`` block out."""
        if call.get("type") != "tool_use" or "name" not in call:
            raise ValidationError("malformed Anthropic tool call: expected a tool_use block")
        raw_input = call.get("input")
        arguments: Mapping[str, object] = raw_input if isinstance(raw_input, Mapping) else {}
        payload, is_error = execute(
            self._gateway, self._descriptor, context, str(call["name"]), arguments
        )
        result: dict[str, object] = {
            "type": "tool_result",
            "tool_use_id": str(call.get("id") or ""),
            "content": [{"type": "text", "text": json.dumps(payload, sort_keys=True)}],
        }
        if is_error:
            result["is_error"] = True
        return result
