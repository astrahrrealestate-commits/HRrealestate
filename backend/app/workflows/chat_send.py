"""`chat:{company_id}:{client_msg_id}`: deliver one owner-typed WhatsApp message from the Chats page (ADR 0013).

The API committed the outbound `messages` row (`delivery_status` NULL) before it enqueued, so a lost enqueue loses
nothing the stuck sweep cannot see. The body only orders steps; every read, write and provider call is inside one.

- `chat.send`: `send_chat_message`. A definitely-not-sent provider error resets the `sends` row to pending and
  re-raises, so the step retries (`SEND_RETRY`); a refusal or an ambiguous failure settles the row as failed and is
  never retried.
- Retries exhausted: the row would stay `delivery_status` NULL with nobody to settle it, so `chat.fail_exhausted`
  marks it failed (only while it is still NULL and its send is neither sent nor sending), then the error is re-raised.
- `in_progress` (another attempt holds the send) ends this run with no change: that attempt reports, or the 5-minute
  sweep (`app.sender.stuck`) settles it. This run never loops and never re-enqueues.
- After a send: `chat.replay_statuses` applies a `delivered`/`read` receipt that arrived before the wamid was stored,
  and `chat.close_suggestion` closes the AI draft the text came from.
"""

from typing import Any
from uuid import UUID

from dbos import DBOS
from sqlalchemy.orm import Session

from app.core.logging import get_logger
from app.core.workflow_names import CHAT_SEND
from app.ingestion import repository
from app.ingestion.process import is_transient
from app.pipeline import chat_close
from app.sender.owner_chat import send_chat_message
from app.sender.owner_chat_settle import fail_exhausted
from app.workflows.deps import get_engine, get_sender_deps
from app.workflows.retry import STEP_RETRY

log = get_logger(__name__)

GAVE_UP = "could not send after several tries; check the chat before sending again"


def _retryable(exc: BaseException) -> bool:
    return bool(getattr(exc, "retryable", False)) or is_transient(exc)


SEND_RETRY: dict[str, Any] = {  # as `actions._RETRY`: only errors that say the message was definitely not sent
    "retries_allowed": True,
    "max_attempts": 6,
    "interval_seconds": 5.0,
    "backoff_rate": 2.0,
    "should_retry": _retryable,
}


@DBOS.step(name="chat.send", **SEND_RETRY)
def send_step(company_id: str, message_id: str) -> list[str]:
    outcome = send_chat_message(get_sender_deps(), UUID(company_id), UUID(message_id))
    return [outcome.status, outcome.reason or "", outcome.provider_ref or ""]


@DBOS.step(name="chat.fail_exhausted", **STEP_RETRY)
def fail_exhausted_step(company_id: str, message_id: str) -> bool:
    return fail_exhausted(get_engine(), UUID(company_id), UUID(message_id), GAVE_UP)


@DBOS.step(name="chat.replay_statuses", **STEP_RETRY)
def replay_statuses_step(company_id: str, wamid: str) -> None:
    with Session(get_engine()) as session, session.begin():
        repository.replay_statuses(session, UUID(company_id), wamid)


@DBOS.step(name="chat.close_suggestion", **STEP_RETRY)
def close_suggestion_step(company_id: str, message_id: str) -> bool:
    return chat_close.close_suggestion(get_engine(), UUID(company_id), UUID(message_id))


@DBOS.workflow(name=CHAT_SEND)
def chat_send_wf(company_id: str, message_id: str) -> str:
    try:
        status, _reason, wamid = send_step(company_id, message_id)
    except Exception as exc:  # retries exhausted (or any error escaping the step): settle the row, then fail the run
        log.error("chat.send_gave_up", message_id=message_id, error=type(exc).__name__)
        fail_exhausted_step(company_id, message_id)
        raise
    if status in ("sent", "already"):  # "already": a replay after the send was recorded; both steps are idempotent
        if wamid:
            replay_statuses_step(company_id, wamid)
        close_suggestion_step(company_id, message_id)
    return status
