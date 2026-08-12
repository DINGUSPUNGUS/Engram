"""Shared wire types."""

from pydantic import BaseModel, Field


class Problem(BaseModel):
    """RFC 9457 problem details — the error shape of every non-2xx response."""

    type: str = "about:blank"
    title: str
    status: int
    detail: str | None = None
    instance: str | None = None


class ProvenanceView(BaseModel):
    """Who or what caused an event (ADR-0021 §3).

    ``detail`` is free-form: for pipeline-opened proposals it is the JSON explanation
    described by ADR-0019 §3 (provider, model ids, prompt versions, scoring inputs);
    for hand-written events it is absent. Clients parse it defensively and never
    infer a value it does not contain (ADR-0022 §4).
    """

    actor: str
    session_id: str | None = None
    detail: str | None = None


class HealthResponse(BaseModel):
    status: str = "ok"


class VersionResponse(BaseModel):
    version: str


PROBLEM_RESPONSES: dict[int | str, dict[str, object]] = {
    "4XX": {"model": Problem, "description": "Problem details (RFC 9457)"},
    "5XX": {"model": Problem, "description": "Problem details (RFC 9457)"},
}

CursorParam = Field(default=None, description="Opaque pagination cursor from a previous page")
LimitParam = Field(default=50, ge=1, le=200, description="Page size")
