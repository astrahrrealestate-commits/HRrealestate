"""Follow-up wiring (#5): the `wait.due` timer handler (chaser or escalation card to Harjot)."""

from datetime import UTC, datetime
from uuid import UUID

from app.core.settings import get_settings
from app.pipeline import followups
from app.pipeline.timers import ClaimedTimer
from app.pipeline.work_repo import WAIT_DUE
from app.workflows import timer_dispatch
from app.workflows.deps import get_engine
from app.workflows.owner_notify import send_card_step


def on_wait_due(timer: ClaimedTimer) -> None:
    """Runs inside the `timers.run_handler` step; replay-safe through the wait's chase step."""
    approval_id = followups.handle_wait_due(
        get_engine(),
        get_settings(),
        timer.company_id,
        UUID(timer.payload["wait_id"]),
        step=int(timer.payload.get("step", 0)),
        now=datetime.now(UTC),
    )
    if approval_id is not None:
        send_card_step(str(timer.company_id), str(approval_id))


timer_dispatch.register(WAIT_DUE, on_wait_due)
