"""Wire shapes for the unversioned operational endpoints (ADR-0021 §2)."""

from pydantic import BaseModel

#: Mirrors ``AssistantGateway.SUPPORTED`` (ADR-0020) as literal strings — the
#: same pattern ``MemoryKindName`` already uses to keep wire schemas decoupled
#: from a domain enum, and here it also keeps ``engram_api`` from taking a new
#: dependency on ``engram_assistants`` (that package builds the pipeline/LLM
#: provider stack; the API only needs the five capability names).
ASSISTANT_CAPABILITIES: tuple[str, ...] = (
    "proposal_submission",
    "retrieval",
    "streaming",
    "timeline",
    "tool_calling",
)


class ProjectionHealthResponse(BaseModel):
    name: str
    checkpoint: int
    lag: int = 0


class StatsResponse(BaseModel):
    event_count: int
    head_global_seq: int
    memory_count: int
    projections: list[ProjectionHealthResponse]
    drifted: bool


class SettingsResponse(BaseModel):
    data_dir: str
    db_path: str
    export_repo_path: str
    export_repo_initialized: bool
    export_paths: list[str]
    assistant_capabilities: list[str]


class RebuildResponse(BaseModel):
    events_replayed: int
