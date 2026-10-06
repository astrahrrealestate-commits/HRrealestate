"""System workflows: liveness self-check and the due-timer sweep."""

from datetime import datetime
from typing import Any

from dbos import DBOS


@DBOS.workflow(name="system.selfcheck")
def selfcheck() -> str:
    """Trivial workflow proving an executor is dequeuing and running work (used by `app.worker --selfcheck`)."""
    return "ok"


@DBOS.workflow(name="system.timer_sweep")
def timer_sweep(scheduled_time: datetime, context: Any) -> None:
    """Claims due `timers` rows and dispatches them. M1: no timer kinds exist yet, so there is nothing to claim."""
