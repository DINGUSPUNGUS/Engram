"""App factory. ``uvicorn engram_api.main:app`` for the module-level default;
tests build isolated instances via :func:`create_app`."""

from threading import Lock

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from engram_api import __version__
from engram_api.config import EngramSettings
from engram_api.errors import register_error_handlers
from engram_api.logging import configure_logging
from engram_api.middleware import RequestContextMiddleware
from engram_api.routers import system
from engram_api.routers.v1 import router as v1_router

_LOCAL_WEB_ORIGINS = ["http://localhost:3000", "http://127.0.0.1:3000"]


def create_app(settings: EngramSettings | None = None) -> FastAPI:
    settings = settings or EngramSettings()
    configure_logging(settings)

    app = FastAPI(
        title="engram API",
        version=__version__,
        description="Git-native, event-sourced, user-owned memory for AI assistants.",
    )
    app.add_middleware(RequestContextMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=_LOCAL_WEB_ORIGINS,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    register_error_handlers(app)
    # Built on first use, not here: constructing an app must not touch the
    # filesystem, or exporting the OpenAPI schema would migrate a database.
    app.state.settings = settings
    app.state.runtime = None
    app.state.runtime_lock = Lock()
    app.include_router(system.router)
    app.include_router(v1_router, prefix="/api/v1")
    return app


app = create_app()
