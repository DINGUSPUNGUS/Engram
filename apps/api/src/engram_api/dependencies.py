"""Dependency injection wiring: the composition root of the API process.

This module is the only place that knows which adapter implements which port.
Swapping SQLite for something else, or the in-process bus for a queued one, is a
change here and nowhere else.
"""

from functools import lru_cache
from typing import Annotated

from fastapi import Depends, Request

from engram_api.config import EngramSettings
from engram_core.application.commands.memory_commands import MemoryCommandService
from engram_core.application.commands.proposal_commands import ProposalCommandService
from engram_core.application.queries.memory_queries import MemoryQueryService
from engram_core.application.queries.search_queries import SearchQueryService
from engram_core.application.queries.timeline_queries import TimelineQueryService
from engram_core.domain.events import build_registry
from engram_events import EventRegistry, InProcessEventBus, Provenance


@lru_cache(maxsize=1)
def get_settings() -> EngramSettings:
    return EngramSettings()


@lru_cache(maxsize=1)
def get_registry() -> EventRegistry:
    return build_registry()


@lru_cache(maxsize=1)
def get_bus() -> InProcessEventBus:
    """Process-wide synchronous bus. Projections subscribe at startup (see main)."""
    return InProcessEventBus()


def get_principal(request: Request) -> Provenance:
    """The reserved authentication seam (docs/security.md).

    Today: everything local is the owning user; the assistant name may arrive via
    the X-Engram-Actor header. The auth milestone replaces this dependency —
    routers already consume a ``Provenance`` and will not change.
    """
    actor = request.headers.get("X-Engram-Actor", "user")
    return Provenance(actor=actor)


def get_memory_commands(
    settings: Annotated[EngramSettings, Depends(get_settings)],
) -> MemoryCommandService:
    """Construct the memory command service with its SQLite-backed ports.

    Architecture phase: adapter construction lands with the event-store milestone.
    """
    raise NotImplementedError


def get_proposal_commands(
    settings: Annotated[EngramSettings, Depends(get_settings)],
) -> ProposalCommandService:
    raise NotImplementedError


def get_memory_queries(
    settings: Annotated[EngramSettings, Depends(get_settings)],
) -> MemoryQueryService:
    raise NotImplementedError


def get_search_queries(
    settings: Annotated[EngramSettings, Depends(get_settings)],
) -> SearchQueryService:
    raise NotImplementedError


def get_timeline_queries(
    settings: Annotated[EngramSettings, Depends(get_settings)],
) -> TimelineQueryService:
    raise NotImplementedError
