"""Quality and audit monitor (#8) crons: outcome capture every 15 minutes, drift snapshots daily."""

from datetime import UTC, date, datetime, timedelta
from functools import partial
from typing import Any
from uuid import UUID
from zoneinfo import ZoneInfo

import sentry_sdk
from dbos import DBOS
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.channels.whatsapp import payloads
from app.core.logging import get_logger
from app.db.models import Company
from app.outcomes.capture import capture_outcomes
from app.outcomes.drift import run_drift
from app.sender.execute import send_to_owner
from app.workflows.deps import get_engine, get_sender_deps

log = get_logger(__name__)


@DBOS.step(name="outcomes.capture")
def capture_step(now_iso: str) -> int:
    return capture_outcomes(get_engine(), datetime.fromisoformat(now_iso))


@DBOS.workflow(name="outcomes.capture_cron")
def capture_cron(scheduled_time: datetime, context: Any) -> None:
    capture_step(scheduled_time.astimezone(UTC).isoformat())


def _text(body: str, to: str) -> dict[str, Any]:
    return payloads.text(to, body)


@DBOS.step(name="drift.companies")
def companies_step(now_iso: str) -> list[tuple[str, str]]:
    """(company id, yesterday in the company's own timezone)."""
    now = datetime.fromisoformat(now_iso)
    with Session(get_engine()) as session:
        rows = session.execute(select(Company.id, Company.timezone)).all()
    return [(str(cid), ((now.astimezone(ZoneInfo(tz))).date() - timedelta(days=1)).isoformat()) for cid, tz in rows]


@DBOS.step(name="drift.run")
def drift_step(company_id: str, day_iso: str) -> int:
    breaches = run_drift(get_engine(), UUID(company_id), date.fromisoformat(day_iso))
    if breaches:
        lines = [f"- {b.metric}: {b.value:.2f} (baseline {b.baseline:.2f})" for b in breaches]
        text = f"Quality alert for {day_iso}:\n" + "\n".join(lines)
        sentry_sdk.capture_message(
            f"drift breach {company_id} {day_iso}: {[b.metric for b in breaches]}", level="warning"
        )
        send_to_owner(get_sender_deps(), UUID(company_id), f"drift:{company_id}:{day_iso}", partial(_text, text))
    return len(breaches)


@DBOS.workflow(name="drift.daily")
def drift_cron(scheduled_time: datetime, context: Any) -> None:
    for company_id, day_iso in companies_step(scheduled_time.astimezone(UTC).isoformat()):
        try:  # one company's failure must not block the others
            drift_step(company_id, day_iso)
        except Exception as exc:
            log.error("drift.failed", company_id=company_id, error=type(exc).__name__)
