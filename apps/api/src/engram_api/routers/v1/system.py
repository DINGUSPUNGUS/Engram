"""/stats, /settings — space health and read-only configuration (ADR-0021 §2).

Neither composes a projection: ``/stats`` forwards ``Runtime.status()`` (log
totals + per-projection checkpoints, the same numbers ``engram status``
prints); ``/settings`` forwards existing ports (``VersionControl``,
``MarkdownSync``) and settings already on the runtime.
"""

from fastapi import APIRouter

from engram_api.dependencies import RuntimeDep
from engram_api.schemas.common import PROBLEM_RESPONSES
from engram_api.schemas.system import (
    ASSISTANT_CAPABILITIES,
    ProjectionHealthResponse,
    SettingsResponse,
    StatsResponse,
)

router = APIRouter(tags=["system"], responses=PROBLEM_RESPONSES)


@router.get("/stats", response_model=StatsResponse)
async def stats(runtime: RuntimeDep) -> StatsResponse:
    """Log totals and per-projection drift — what ``engram status`` computes,
    over HTTP. A drifted projection recovers with ``POST /admin/rebuild``."""
    space = runtime.status()
    return StatsResponse(
        event_count=space.event_count,
        head_global_seq=space.head_global_seq,
        memory_count=space.memory_count,
        projections=[
            ProjectionHealthResponse(name=p.name, checkpoint=p.checkpoint, lag=p.lag)
            for p in space.projections
        ],
        drifted=space.drifted,
    )


@router.get("/settings", response_model=SettingsResponse)
async def settings_view(runtime: RuntimeDep) -> SettingsResponse:
    """Gateway capabilities, export/git status, and export paths — existing
    configuration and ports, read-only; nothing here is mutable yet."""
    return SettingsResponse(
        data_dir=str(runtime.settings.data_dir),
        db_path=str(runtime.settings.resolved_db_path),
        export_repo_path=str(runtime.settings.resolved_export_repo),
        export_repo_initialized=runtime.git.is_repo(),
        export_paths=[str(p) for p in runtime.reconciler.export_paths()],
        assistant_capabilities=list(ASSISTANT_CAPABILITIES),
    )
