"""Pipeline entry DBOS workflow: triage inbound messages, link cases, propose actions."""

from datetime import UTC, datetime
from functools import partial
from typing import Any
from uuid import UUID

from dbos import DBOS, SetWorkflowID
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.channels.whatsapp import payloads
from app.core.logging import get_logger
from app.core.settings import get_settings
from app.core.workflow_names import PIPELINE_ENTRY
from app.db.models import AttachmentRow, MessageRow
from app.directory.identity import resolve_message_sender
from app.ingestion.process import is_transient
from app.llm.calls import is_transient as llm_transient
from app.pipeline.link import link_message
from app.pipeline.propose import propose_for_message
from app.pipeline.understand import (
    mark_pipeline_done,
    mark_pipeline_failed,
    requeue_candidates,
    understand_message,
    understanding_is_final_failure,
)
from app.workflows import queues
from app.workflows.deps import get_engine
from app.workflows.documents import enqueue_filing
from app.workflows.owner_notify import alert_exceptions_step, send_card_step, send_owner_message

log = get_logger(__name__)


def _retryable(exc: BaseException) -> bool:
    return bool(getattr(exc, "retryable", False)) or is_transient(exc) or llm_transient(exc)


_RETRY: dict[str, Any] = {
    "retries_allowed": True,
    "max_attempts": 5,
    "interval_seconds": 2.0,
    "backoff_rate": 2.0,
    "should_retry": _retryable,
}


@DBOS.step(name="pipeline.understand", **_RETRY)
def understand_step(message_id: str) -> str:
    engine = get_engine()
    settings = get_settings()
    return "understood" if understand_message(engine, settings, UUID(message_id)) is not None else "failed"


@DBOS.step(name="pipeline.final_failure", **_RETRY)
def final_failure_step(message_id: str) -> bool:
    """Its own step: a DB blip here must never re-run the LLM call above."""
    return understanding_is_final_failure(get_engine(), UUID(message_id))


@DBOS.step(name="pipeline.mark_failed", **_RETRY)
def mark_failed_step(message_id: str, error: str) -> int:
    return mark_pipeline_failed(get_engine(), UUID(message_id), error)


@DBOS.step(name="pipeline.alert_unreadable", **_RETRY)
def alert_unreadable_step(company_id: str, message_id: str) -> bool:
    text = (
        "EstateOS could not read a new message after 3 attempts. It is on its own case (category 'other'); "
        "please look at it yourself."
    )
    return send_owner_message(company_id, f"unreadable:{message_id}", partial(_text, text))


@DBOS.step(name="pipeline.resolve_sender", **_RETRY)
def resolve_step(message_id: str) -> None:
    resolve_message_sender(get_engine(), UUID(message_id))


@DBOS.step(name="pipeline.link", **_RETRY)
def link_step(message_id: str) -> str | None:
    result = link_message(get_engine(), get_settings(), UUID(message_id))
    return str(result.case_id) if result else None


@DBOS.step(name="pipeline.propose", **_RETRY)
def propose_step(message_id: str) -> dict[str, Any]:
    result = propose_for_message(get_engine(), get_settings(), UUID(message_id))
    return {"approval_ids": [str(a) for a in result.approval_ids], "exceptions": result.exceptions}


@DBOS.step(name="pipeline.company")
def company_step(message_id: str) -> str | None:
    with Session(get_engine()) as session:
        msg = session.get(MessageRow, UUID(message_id))
        return str(msg.company_id) if msg else None


@DBOS.step(name="pipeline.attachments")
def attachments_step(message_id: str) -> list[str]:
    with Session(get_engine()) as session:
        msg = session.get(MessageRow, UUID(message_id))
        if msg is None:
            return []
        rows = session.scalars(
            select(AttachmentRow.id).where(
                AttachmentRow.company_id == msg.company_id, AttachmentRow.message_id == msg.id
            )
        ).all()
        return [str(r) for r in rows]


@DBOS.step(name="pipeline.done")
def done_step(message_id: str) -> None:
    mark_pipeline_done(get_engine(), UUID(message_id))


def _text(body: str, to: str) -> dict[str, Any]:
    return payloads.text(to, body)


def _after_understanding(message_id: str, final_failure: bool) -> bool:
    resolve_step(message_id)
    case_id = link_step(message_id)
    company_id = company_step(message_id)
    if case_id is None or company_id is None:
        return False
    if final_failure:
        alert_unreadable_step(company_id, message_id)
    proposed = propose_step(message_id)
    for approval_id in proposed["approval_ids"]:
        send_card_step(company_id, approval_id)
    if proposed["exceptions"]:
        alert_exceptions_step(company_id, message_id)
    for attachment_id in attachments_step(message_id):  # #9: file after linking (needs the case context)
        enqueue_filing(company_id, attachment_id)
    return True


@DBOS.workflow(name=PIPELINE_ENTRY)
def pipeline_entry(message_id: str) -> str:
    """Orchestrator (#1): understand → resolve sender → link → propose + rules → ask owner. One step per stage.

    A failed understanding with attempts left stops here (the hourly requeue retries it); the final failure still
    opens an `other` case and tells Harjot. Any stage that outlives its retries marks the message for the requeue.
    """
    try:
        status = understand_step(message_id)
        if status == "failed":
            if not final_failure_step(message_id):
                return "failed"
            status = "final"
        linked = _after_understanding(message_id, final_failure=status == "final")
        done_step(message_id)
    except Exception as exc:  # DBOS cancellation is a BaseException and is not caught
        mark_failed_step(message_id, f"{type(exc).__name__}: {str(exc)[:200]}")
        raise
    log.info("pipeline.entry.done", message_id=message_id, status=status, linked=linked)
    return "understood" if status == "understood" else "failed"


@DBOS.step(name="pipeline.requeue_candidates")
def requeue_candidates_step(now_iso: str) -> list[tuple[str, str]]:
    """Messages whose pipeline run is still waiting in a queue are skipped: a rerun would only race it."""
    candidates = requeue_candidates(get_engine(), datetime.fromisoformat(now_iso))
    if not candidates:
        return []
    queued = {w.workflow_id.split(":")[1] for w in DBOS.list_workflows(workflow_id_prefix="pipe:", status="ENQUEUED")}
    return [(str(mid), wf) for mid, wf in candidates if str(mid) not in queued]


@DBOS.workflow(name="pipeline.requeue")
def requeue_failed(scheduled_time: datetime, context: Any) -> None:
    """Hourly: rerun failed pipeline runs (max 3 attempts per message) and messages stranded in `pending`."""
    for message_id, workflow_id in requeue_candidates_step(scheduled_time.astimezone(UTC).isoformat()):
        with SetWorkflowID(workflow_id):
            queues.pipeline_queue().enqueue(pipeline_entry, message_id)
