"""Dependency injection wiring: the composition root of the API process.

Construction lives in :mod:`engram_api.runtime`; this module is the FastAPI-facing
half — it resolves the per-app :class:`~engram_api.runtime.Runtime` and hands
routers exactly the one service each needs. Routers depend on services, never on
the runtime as a whole, so a router cannot reach a port it has no business calling.
"""

from functools import lru_cache
from typing import Annotated

from fastapi import Depends, Request

from engram_api.config import EngramSettings
from engram_api.runtime import Runtime, build_runtime
from engram_core.application.commands.memory_commands import MemoryCommandService
from engram_core.application.commands.proposal_commands import ProposalCommandService
from engram_core.application.queries.history_queries import HistoryQueryService
from engram_core.application.queries.memory_queries import MemoryQueryService
from engram_core.application.queries.proposal_queries import ProposalQueryService
from engram_core.application.queries.search_queries import SearchQueryService
from engram_core.application.queries.timeline_queries import TimelineQueryService
from engram_core.domain.events import build_registry
from engram_core.domain.kinds import KindRegistry, build_kind_registry
from engram_events import EventRegistry, Provenance


@lru_cache(maxsize=1)
def get_settings() -> EngramSettings:
    return EngramSettings()


@lru_cache(maxsize=1)
def get_registry() -> EventRegistry:
    return build_registry()


@lru_cache(maxsize=1)
def get_kind_registry() -> KindRegistry:
    return build_kind_registry()


def get_runtime(request: Request) -> Runtime:
    """The app's runtime, constructed on first use and cached on ``app.state``.

    Per-app rather than process-global so tests can stand up isolated instances
    against their own databases. Deferred rather than built in ``create_app`` so
    that merely constructing an app — as ``export_openapi`` does — never migrates
    a database.
    """
    state = request.app.state
    if state.runtime is None:
        with state.runtime_lock:
            if state.runtime is None:
                state.runtime = build_runtime(state.settings)
    return state.runtime  # type: ignore[no-any-return]


RuntimeDep = Annotated[Runtime, Depends(get_runtime)]


def get_principal(request: Request) -> Provenance:
    """The reserved authentication seam (docs/security.md).

    Today: everything local is the owning user; the assistant name may arrive via
    the X-Engram-Actor header. The auth milestone replaces this dependency —
    routers already consume a ``Provenance`` and will not change.
    """
    actor = request.headers.get("X-Engram-Actor", "user")
    session_id = request.headers.get("X-Engram-Session")
    return Provenance(actor=actor, session_id=session_id)


def get_memory_commands(runtime: RuntimeDep) -> MemoryCommandService:
    return runtime.commands


def get_proposal_commands(runtime: RuntimeDep) -> ProposalCommandService:
    return runtime.proposals


def get_memory_queries(runtime: RuntimeDep) -> MemoryQueryService:
    return runtime.queries


def get_proposal_queries(runtime: RuntimeDep) -> ProposalQueryService:
    return runtime.proposal_queries


def get_search_queries(runtime: RuntimeDep) -> SearchQueryService:
    return runtime.search


def get_timeline_queries(runtime: RuntimeDep) -> TimelineQueryService:
    return runtime.timeline


def get_history_queries(runtime: RuntimeDep) -> HistoryQueryService:
    return runtime.history
