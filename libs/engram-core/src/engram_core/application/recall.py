"""The recall-visibility policy (memory-model.md §3, ADR-0020).

Core owns the rule; the assistant gateway is the boundary that applies it. The CLI
and dashboard are *user* surfaces and deliberately do not filter — visibility
governs what assistants may recall, not what the owner may see.

The rule, in full:

- ``shared``      — any connected assistant may recall it (the default).
- ``private``     — never surfaced to an assistant. A hidden memory must be
                    indistinguishable from an absent one, so callers translate a
                    failed check into the same NotFoundError an unknown id gets.
- ``restricted``  — only actors on the memory's allow-list.

Archived memories are additionally never recallable: they are hidden from recall
by definition (memory-model.md §4).
"""

from engram_core.application.dto import MemoryReadModel

_SHARED = "shared"
_RESTRICTED = "restricted"


def recallable(memory: MemoryReadModel, actor: str) -> bool:
    """May ``actor`` (an assistant identity) recall this memory? Pure."""
    if memory.archived:
        return False
    if memory.visibility == _SHARED:
        return True
    if memory.visibility == _RESTRICTED:
        return actor in memory.allowed_actors
    return False  # private, and any unknown future visibility fails closed
