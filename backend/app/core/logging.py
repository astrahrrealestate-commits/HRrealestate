"""structlog setup: JSON lines outside dev, pretty console in dev. Context binds via contextvars; redaction last."""

import logging

import structlog

from app.core.redaction import ChatPathFilter, redact_event


def configure_logging(env: str) -> None:
    renderer: structlog.typing.Processor = (
        structlog.dev.ConsoleRenderer() if env == "dev" else structlog.processors.JSONRenderer()
    )
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            redact_event,  # last before rendering: secrets, BRIXX personal columns and rows never leave
            renderer,
        ],
        wrapper_class=structlog.make_filtering_bound_logger(logging.INFO),
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=False,
    )
    _mask_access_log_paths()


def _mask_access_log_paths() -> None:
    """uvicorn's access log is the only request log: keep contact numbers out of its paths."""
    access = logging.getLogger("uvicorn.access")
    if not any(isinstance(f, ChatPathFilter) for f in access.filters):
        access.addFilter(ChatPathFilter())


def get_logger(name: str) -> structlog.typing.FilteringBoundLogger:
    logger: structlog.typing.FilteringBoundLogger = structlog.get_logger(name)
    return logger
