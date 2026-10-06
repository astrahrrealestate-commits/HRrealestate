"""Liveness (process up) and readiness (can serve: database reachable). Worker readiness: `app.worker --selfcheck`."""

from typing import Annotated, Any

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from sqlalchemy import Engine, text
from sqlalchemy.exc import SQLAlchemyError

import app
from app.api.deps import get_engine
from app.core.logging import get_logger

router = APIRouter(prefix="/health", tags=["health"])
log = get_logger(__name__)


@router.get("/live")
async def live() -> dict[str, str]:
    """No I/O, so async: never queues behind threadpool work (e.g. slow readiness checks)."""
    return {"status": "ok", "version": app.__version__}


@router.get("/ready", response_model=None)
def ready(engine: Annotated[Engine, Depends(get_engine)]) -> dict[str, Any] | JSONResponse:
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
    except SQLAlchemyError as exc:
        log.warning("health.ready.database_error", error_type=type(exc).__name__)  # no message: may contain DSN
        return JSONResponse(status_code=503, content={"status": "unavailable", "checks": {"database": "error"}})
    return {"status": "ready"}
