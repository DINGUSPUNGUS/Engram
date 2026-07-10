"""Unversioned operational endpoints."""

from fastapi import APIRouter, status

from engram_api import __version__
from engram_api.schemas.common import PROBLEM_RESPONSES, HealthResponse, VersionResponse

router = APIRouter(tags=["system"])


@router.get("/healthz", response_model=HealthResponse)
async def healthz() -> HealthResponse:
    """Liveness. Will grow readiness details (db reachable, projections caught up)."""
    return HealthResponse()


@router.get("/version", response_model=VersionResponse)
async def version() -> VersionResponse:
    return VersionResponse(version=__version__)


@router.post("/admin/rebuild", status_code=status.HTTP_202_ACCEPTED, responses=PROBLEM_RESPONSES)
async def rebuild_projections() -> dict[str, str]:
    """Replay the event log through every projection from global_seq 0."""
    raise NotImplementedError
