"""System workflows: liveness self-check and the due-timer sweep."""

from datetime import datetime
from typing import Any

from dbos import DBOS

from app.workflows import timer_dispatch


@DBOS.workflow(name="system.selfcheck")
def selfcheck() -> str:
    """Trivial workflow proving an executor is dequeuing and running work (used by `app.worker --selfcheck`)."""
    return "ok"


@DBOS.workflow(name="system.timer_sweep")
def timer_sweep(scheduled_time: datetime, context: Any) -> None:
    """Every minute: claim due `timers` rows and fire one `timers.fire` workflow per claim (child workflow)."""
    timer_dispatch.sweep_due(scheduled_time)
