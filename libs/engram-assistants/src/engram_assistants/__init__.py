"""engram-assistants: the assistant integration layer (ADR-0020).

One provider-agnostic gateway defines everything an assistant may do; provider
adapters (ChatGPT, Claude, Gemini, …) translate wire formats and nothing else.
The tool surface has no review verbs — nothing an assistant submits becomes
memory until a human approves and merges the proposal.
"""

from engram_assistants.contract import (
    AdapterDescriptor,
    AssistantAdapter,
    AssistantContext,
    Capability,
    CapabilityError,
)
from engram_assistants.gateway import AssistantGateway, RecalledMemory
from engram_assistants.rendering import render_context_block
from engram_assistants.tools import TOOLS

__all__ = [
    "TOOLS",
    "AdapterDescriptor",
    "AssistantAdapter",
    "AssistantContext",
    "AssistantGateway",
    "Capability",
    "CapabilityError",
    "RecalledMemory",
    "render_context_block",
]
