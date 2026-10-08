"""Briefing wiring (#7): hourly cron keeps the next runs scheduled; timer handlers compose and send to Harjot."""

from datetime import UTC, datetime
from functools import partial
from typing import Any

from dbos import DBOS
from sqlalchemy.orm import Session

from app.channels.whatsapp import payloads
from app.core.settings import get_settings
from app.llm.agents.briefing import Kind
from app.pipeline import briefing
from app.pipeline.timers import ClaimedTimer
from app.sender.execute import send_to_owner
from app.workflows import timer_dispatch
from app.workflows.deps import get_engine, get_sender_deps


def _text(body: str, to: str) -> dict[str, Any]:
    return payloads.text(to, body)


def on_briefing(timer: ClaimedTimer) -> None:
    """Runs inside the `timers.run_handler` step. One send key per timer, so a re-fired timer sends nothing twice;
    outside the WhatsApp window the briefing waits behind the template nudge until Harjot replies."""
    kind: Kind = "weekly" if timer.kind == briefing.WEEKLY else "daily"
    now = datetime.now(UTC)
    with Session(get_engine()) as session, session.begin():  # book the next runs first: a failed send never stops them
        briefing.ensure_timers(session, now)
    text = briefing.compose(get_engine(), get_settings(), timer.company_id, kind, now)
    send_to_owner(get_sender_deps(), timer.company_id, f"briefing:{timer.id}", partial(_text, text))


@DBOS.step(name="briefing.ensure_timers")
def ensure_step(now_iso: str) -> int:
    with Session(get_engine()) as session, session.begin():
        return briefing.ensure_timers(session, datetime.fromisoformat(now_iso))


@DBOS.workflow(name="briefing.ensure")
def ensure_briefings(scheduled_time: datetime, context: Any) -> None:
    ensure_step(scheduled_time.isoformat())


timer_dispatch.register(briefing.DAILY, on_briefing)
timer_dispatch.register(briefing.WEEKLY, on_briefing)
