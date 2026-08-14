"""The one place domain errors become HTTP: RFC 9457 application/problem+json.

Routers and services never construct HTTP errors; they raise ``EngramError``
subclasses (or, in the architecture phase, ``NotImplementedError``) and these
handlers translate exactly once.
"""

import structlog
from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException
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

    @app.exception_handler(RequestValidationError)
    async def handle_request_validation_error(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        """FastAPI's own request-parsing failures (a missing/out-of-range query
        param, an unparseable path param, a malformed body) run before any
        router body executes, so they never reach ``handle_engram_error`` above
        — but every operation's OpenAPI schema still promises its 4XX response
        is this Problem shape (``PROBLEM_RESPONSES``). Without this handler,
        FastAPI's own default renders ``{"detail": [...]}`` instead — a plain
        list of objects, not ``application/problem+json``, silently breaking
        that contract and handing the dashboard's error path a ``detail`` shape
        (a list) its own type (``string | null``) doesn't allow for (PRE-M10
        GATE finding, API/dashboard P1)."""
        detail = "; ".join(
            f"{'.'.join(str(part) for part in err['loc'])}: {err['msg']}" for err in exc.errors()
        )
        return _problem(request, 422, "Validation failed", detail)

    @app.exception_handler(StarletteHTTPException)
    async def handle_http_exception(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        """Starlette's own routing failures — an unmatched path (404), a
        method the route doesn't support (405), and so on — never reach
        ``handle_engram_error`` either, for the same reason and with the same
        fix as ``handle_request_validation_error`` above."""
        detail = exc.detail if isinstance(exc.detail, str) else str(exc.detail)
        return _problem(request, exc.status_code, "HTTP error", detail)
