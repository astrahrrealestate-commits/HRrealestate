"""`exec:{action_id}:{draft_version}`: deliver (sender) or apply (internal) one approved action, exactly once."""

from datetime import UTC, datetime
from functools import partial
from typing import Any
from uuid import UUID

from dbos import DBOS
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.channels.whatsapp import payloads
from app.contracts import ActionType
from app.core.workflow_names import EXECUTE_ACTION
from app.db.models import ActionRow
from app.ingestion.process import is_transient
from app.pipeline import followups, local_actions
from app.sender.execute import execute_action
from app.sender.tenant_gate import blocked_key, blocked_text
from app.workflows.deps import get_engine, get_sender_deps
from app.workflows.finance import snapshot_after_approval
from app.workflows.owner_notify import send_owner_message
from app.workflows.retry import STEP_RETRY


def _retryable(exc: BaseException) -> bool:
    return bool(getattr(exc, "retryable", False)) or is_transient(exc)


_RETRY: dict[str, Any] = {
    "retries_allowed": True,
    "max_attempts": 6,
    "interval_seconds": 5.0,
    "backoff_rate": 2.0,
    "should_retry": _retryable,
}


@DBOS.step(name="actions.apply_local", **_RETRY)
def apply_local_step(action_id: str, draft_version: int) -> str:
    return local_actions.apply_local(get_engine(), UUID(action_id), draft_version)


@DBOS.step(name="actions.send", **_RETRY)
def send_step(action_id: str, draft_version: int) -> list[str]:
    outcome = execute_action(get_sender_deps(), UUID(action_id), draft_version)
    return [outcome.status, outcome.reason or ""]


@DBOS.step(name="actions.tell_blocked", **STEP_RETRY)
def tell_blocked_step(action_id: str, draft_version: int, reason: str) -> None:
    """An approved action could not run: Harjot hears why (and that `resume` retries a paused one). Keyed by
    `blocked_key` (the sender's tenant alert key too), never the workflow id, so a resume run adds no second alert:
    a dashboard owner keeps the one feed row, a WhatsApp/Chat owner gets one message. A tenant reply uses the
    dashboard alert's wording (`tenant_gate.alert_text`), never "not sent" when the tenant may have it."""
    with Session(get_engine()) as session:
        row = session.execute(
            select(ActionRow.company_id, ActionRow.type).where(ActionRow.id == UUID(action_id))
        ).first()
    if row is None:
        return
    text = blocked_text(reason, tenant_reply=row[1] is ActionType.reply_draft)
    send_owner_message(str(row[0]), blocked_key(UUID(action_id), draft_version), partial(_text, text))


def _text(body: str, to: str) -> dict[str, Any]:
    return payloads.text(to, body)


@DBOS.step(name="actions.after_execute", **STEP_RETRY)
def after_execute_step(action_id: str) -> str | None:
    """Sent requests wait for an answer (#5): open the wait that the chase ladder watches."""
    wait_id = followups.open_waits_after_execute(get_engine(), UUID(action_id), now=datetime.now(UTC))
    return str(wait_id) if wait_id else None


EXHAUSTED = "could not send after retries; the approval is still valid"


def _send_or_tell(action_id: str, draft_version: int) -> list[str]:
    """Retries exhausted (or any error escaping the step): Harjot hears it, the `sends` row stays pending for a
    later resume, and the error is re-raised so the workflow ends in ERROR, never looking successful."""
    try:
        return send_step(action_id, draft_version)
    except Exception:
        tell_blocked_step(action_id, draft_version, EXHAUSTED)  # no exception text: it may quote a body
        raise


@DBOS.workflow(name=EXECUTE_ACTION)
def execute_action_wf(action_id: str, draft_version: int, local: bool) -> str:
    snapshot_after_approval(action_id)  # first: the approval fixes the decision day (R24), whatever happens next
    if local:
        outcome, reason = apply_local_step(action_id, draft_version), "company paused or approval no longer valid"
    else:
        outcome, reason = _send_or_tell(action_id, draft_version)
    if outcome in ("sent", "already"):  # "already": a replay after the send was recorded; open_wait is idempotent
        after_execute_step(action_id)
    elif outcome in ("blocked", "failed"):  # Harjot always hears when an approved action did not go out
        tell_blocked_step(action_id, draft_version, reason)
    # "in_progress": another attempt holds the send; it reports, or the stuck sweep settles it. No wait, no alert.
    return outcome
