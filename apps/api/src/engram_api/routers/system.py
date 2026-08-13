"""Unversioned operational endpoints. ``/stats``/``/settings`` are versioned
(``/api/v1/...``) and live in :mod:`engram_api.routers.v1.system` instead."""

from fastapi import APIRouter, status

from engram_api import __version__
from engram_api.dependencies import RuntimeDep
from engram_api.schemas.common import PROBLEM_RESPONSES, HealthResponse, VersionResponse
from engram_api.schemas.system import RebuildResponse

router = APIRouter(tags=["system"])


@router.get("/healthz", response_model=HealthResponse)
async def healthz() -> HealthResponse:
    """Liveness. Will grow readiness details (db reachable, projections caught up)."""
    return HealthResponse()


@router.get("/version", response_model=VersionResponse)
async def version() -> VersionResponse:
    return VersionResponse(version=__version__)


@router.post(
    "/admin/rebuild",
    response_model=RebuildResponse,
    status_code=status.HTTP_202_ACCEPTED,
    responses=PROBLEM_RESPONSES,
)
async def rebuild_projections(runtime: RuntimeDep) -> RebuildResponse:
    """Replay the event log through every projection from global_seq 0
    (ADR-0021 §2) — the disposability contract, over HTTP. Synchronous: for a
    local-first single-user space the replay is fast enough that a background
    job would only add a status-polling surface with nothing yet to poll for."""
    return RebuildResponse(events_replayed=runtime.rebuild())
