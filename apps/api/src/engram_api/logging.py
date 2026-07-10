"""structlog configuration: pretty console in dev, JSON lines in prod.

The domain layer never logs — the event log is its audit trail. Interface and
adapter layers log operational context, always through structlog, always with the
request id bound (see middleware).
"""

import logging

import structlog

from engram_api.config import EngramSettings


def configure_logging(settings: EngramSettings) -> None:
    """Idempotent process-wide logging setup."""
    renderer: structlog.types.Processor
    if settings.log_format == "json":
        renderer = structlog.processors.JSONRenderer()
    else:
        renderer = structlog.dev.ConsoleRenderer()

    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            renderer,
        ],
        wrapper_class=structlog.make_filtering_bound_logger(
            logging.getLevelNamesMapping().get(settings.log_level.upper(), logging.INFO)
        ),
        cache_logger_on_first_use=True,
    )
