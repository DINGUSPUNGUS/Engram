"""Shared adapter plumbing: run one canonical call, capture typed failure.

Kept private to ``adapters/`` — everything here is translation support, and every
error an assistant can cause comes back as a well-formed payload, never a crash
(graceful degradation, ADR-0020 §2).
"""

from collections.abc import Mapping
from typing import Any

from engram_assistants.contract import AdapterDescriptor, AssistantContext
from engram_assistants.gateway import AssistantGateway
from engram_assistants.tools import dispatch
from engram_core.domain.errors import EngramError


def execute(
    gateway: AssistantGateway,
    descriptor: AdapterDescriptor,
    context: AssistantContext,
    name: str,
    arguments: Mapping[str, object],
) -> tuple[dict[str, Any], bool]:
    """Dispatch one canonical tool call; returns ``(payload, is_error)``."""
    try:
        return dispatch(gateway, descriptor, context, name, arguments), False
    except EngramError as exc:
        return {"error": str(exc), "error_type": type(exc).__name__}, True
