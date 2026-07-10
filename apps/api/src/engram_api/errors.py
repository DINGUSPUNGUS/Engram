"""The one place domain errors become HTTP: RFC 9457 application/problem+json.

Routers and services never construct HTTP errors; they raise ``EngramError``
subclasses (or, in the architecture phase, ``NotImplementedError``) and these
handlers translate exactly once.
"""

import structlog
from fastapi import FastAPI
from starlette.requests import Request
from starlette.responses import JSONResponse

from engram_core.domain.errors import (
    ConflictError,
    EngramError,
    NotFoundError,
    StaleVersionError,
    StorageError,
    ValidationError,
)

_log = structlog.get_logger(__name__)

PROBLEM_CONTENT_TYPE = "application/problem+json"

# Most-derived first: MRO decides, so StaleVersionError must precede ConflictError.
_STATUS_BY_TYPE: list[tuple[type[EngramError], int, str]] = [
    (ValidationError, 422, "Validation failed"),
    (NotFoundError, 404, "Not found"),
    (StaleVersionError, 409, "Stale version"),
    (ConflictError, 409, "Conflict"),
    (StorageError, 500, "Storage failure"),
]


def _problem(request: Request, status: int, title: str, detail: str) -> JSONResponse:
    return JSONResponse(
        status_code=status,
        media_type=PROBLEM_CONTENT_TYPE,
        content={
            "type": "about:blank",
            "title": title,
            "status": status,
            "detail": detail,
            "instance": str(request.url.path),
        },
    )


def register_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(EngramError)
    async def handle_engram_error(request: Request, exc: EngramError) -> JSONResponse:
        for error_type, status, title in _STATUS_BY_TYPE:
            if isinstance(exc, error_type):
                if status >= 500:
                    _log.error("engram_error", error=type(exc).__name__, detail=str(exc))
                return _problem(request, status, title, str(exc))
        _log.error("unmapped_engram_error", error=type(exc).__name__)
        return _problem(request, 500, "Internal error", str(exc))

    @app.exception_handler(NotImplementedError)
    async def handle_not_implemented(request: Request, exc: NotImplementedError) -> JSONResponse:
        return _problem(
            request,
            501,
            "Not implemented",
            "engram is in its architecture phase; this endpoint is specified but not built yet.",
        )
