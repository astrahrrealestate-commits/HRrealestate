"""Quality and audit monitor (#8) crons: outcome capture every 15 minutes."""

from datetime import UTC, datetime
from typing import Any

from dbos import DBOS

from app.outcomes.capture import capture_outcomes
from app.workflows.deps import get_engine


@DBOS.step(name="outcomes.capture")
def capture_step(now_iso: str) -> int:
    return capture_outcomes(get_engine(), datetime.fromisoformat(now_iso))


@DBOS.workflow(name="outcomes.capture_cron")
def capture_cron(scheduled_time: datetime, context: Any) -> None:
    capture_step(scheduled_time.astimezone(UTC).isoformat())
