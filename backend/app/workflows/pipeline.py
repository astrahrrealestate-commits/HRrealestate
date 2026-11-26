"""Pipeline entry DBOS workflow: triage inbound messages, link cases, propose actions."""

from datetime import UTC, datetime
from functools import partial
from typing import Any
from uuid import UUID

from dbos import DBOS, SetEnqueueOptions, SetWorkflowID
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.channels.whatsapp import payloads
from app.context.message_origin import is_history
from app.core.errors import BudgetExceededError
from app.core.logging import get_logger
from app.core.settings import get_settings
from app.core.workflow_names import PIPELINE_ENTRY
from app.db.models import AttachmentRow, MessageRow
from app.directory.identity import resolve_message_sender
from app.ingestion.process import is_transient
from app.llm.calls import is_transient as llm_transient
from app.pipeline import case_repo
from app.pipeline.link import link_message
from app.pipeline.person_memory import refresh_for_message
from app.pipeline.propose import propose_for_message
from app.pipeline.understand import (
    history_partitions,
    mark_pipeline_done,
    mark_pipeline_failed,
    requeue_candidates,
    understand_message,
    understanding_is_final_failure,
)
from app.tools.message_rag import index_message
from app.workflows import queues
from app.workflows.deps import get_engine
from app.workflows.documents import enqueue_filing
from app.workflows.finance import quote_after_understanding
from app.workflows.owner_notify import alert_exceptions_step, send_card_step, send_owner_message
from app.workflows.prepare import prepare_for_draft

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


def _as_uuid(val: Any) -> UUID:
    return val if isinstance(val, UUID) else UUID(str(val))


@DBOS.step(name="pipeline.understand", **_RETRY)
def understand_step(message_id: str) -> str:
    engine = get_engine()
    settings = get_settings()
    try:
        return "understood" if understand_message(engine, settings, _as_uuid(message_id)) is not None else "failed"
    except BudgetExceededError:
        return "budget"


@DBOS.step(name="pipeline.alert_budget", **_RETRY)
def alert_budget_step(company_id: str) -> bool:
    """One alert per company per UTC day: the sender key is the idempotency key."""
    day = f"{datetime.now(UTC):%Y%m%d}"
    text = (
        "EstateOS reached its AI usage limit. New messages wait and are retried every hour until the limit resets "
        "or is raised."
    )
    return send_owner_message(company_id, f"budget:{company_id}:{day}", partial(_text, text))


@DBOS.step(name="pipeline.final_failure", **_RETRY)
def final_failure_step(message_id: str) -> bool:
    """Its own step: a DB blip here must never re-run the LLM call above."""
    return understanding_is_final_failure(get_engine(), _as_uuid(message_id))


@DBOS.step(name="pipeline.mark_failed", **_RETRY)
def mark_failed_step(message_id: str, error: str) -> int:
    return mark_pipeline_failed(get_engine(), _as_uuid(message_id), error)


@DBOS.step(name="pipeline.alert_unreadable", **_RETRY)
def alert_unreadable_step(company_id: str, message_id: str) -> bool:
    text = (
        "EstateOS could not read a new message after 3 attempts. It is on its own case under Administration; "
        "please look at it yourself."
    )
    return send_owner_message(company_id, f"unreadable:{message_id}", partial(_text, text))


@DBOS.step(name="pipeline.resolve_sender", **_RETRY)
def resolve_step(message_id: str) -> None:
    resolve_message_sender(get_engine(), _as_uuid(message_id))


@DBOS.step(name="pipeline.index_message", **_RETRY)
def index_message_step(message_id: str) -> str:
    try:
        return index_message(get_engine(), get_settings(), _as_uuid(message_id))
    except Exception as exc:
        log.warning("pipeline.index_message_failed", error=str(exc), message_id=message_id)
        return "failed"


@DBOS.step(name="pipeline.link", **_RETRY)
def link_step(message_id: str) -> str | None:
    result = link_message(get_engine(), get_settings(), _as_uuid(message_id))
    return str(result.case_id) if result else None


@DBOS.step(name="pipeline.prepare")  # no retries: reading, quote review and research never hold up the draft
def prepare_step(message_id: str, research: bool = True) -> None:
    prepare_for_draft(get_engine(), get_settings(), _as_uuid(message_id), research=research)


@DBOS.step(name="pipeline.person_memory")  # no retries: a slow model must not hold up the draft
def person_memory_step(message_id: str) -> None:
    refresh_for_message(get_engine(), get_settings(), _as_uuid(message_id))


@DBOS.step(name="pipeline.propose", **_RETRY)
def propose_step(message_id: str) -> dict[str, Any]:
    result = propose_for_message(get_engine(), get_settings(), _as_uuid(message_id))
    return {"approval_ids": [str(a) for a in result.approval_ids], "exceptions": result.exceptions}


@DBOS.step(name="pipeline.company")
def company_step(message_id: str) -> str | None:
    with Session(get_engine()) as session:
        msg = session.get(MessageRow, _as_uuid(message_id))
        return str(msg.company_id) if msg else None


@DBOS.step(name="pipeline.history")
def history_step(message_id: str) -> bool:
    """Reloaded mail (M13): understood, linked, indexed and filed; never drafted and never announced to Harjot."""
    with Session(get_engine()) as session:
        msg = session.get(MessageRow, _as_uuid(message_id))
        return msg is not None and is_history(msg)


@DBOS.step(name="pipeline.link_sent_history", **_RETRY)
def link_sent_history_step(message_id: str, case_id: str) -> list[str]:
    """Our own sent mail of the same thread, stored before this case existed."""
    with Session(get_engine()) as session, session.begin():
        msg = session.get(MessageRow, _as_uuid(message_id))
        if msg is None:
            return []
        return [str(m) for m in case_repo.link_thread_outbound(session, msg.company_id, _as_uuid(case_id), msg)]


@DBOS.step(name="pipeline.attachments")
def attachments_step(message_id: str) -> list[str]:
    with Session(get_engine()) as session:
        msg = session.get(MessageRow, _as_uuid(message_id))
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
    mark_pipeline_done(get_engine(), _as_uuid(message_id))


def _text(body: str, to: str) -> dict[str, Any]:
    return payloads.text(to, body)


def _index(message_id: str) -> None:
    try:
        index_message_step(message_id)
    except Exception as exc:
        log.warning("pipeline.index_step_failed", error=str(exc), message_id=message_id)


def _live(company_id: str, message_id: str, final_failure: bool) -> None:
    """Live mail only: Harjot hears about it, and it is drafted."""
    if final_failure:
        alert_unreadable_step(company_id, message_id)
    _index(message_id)
    try:
        prepare_step(message_id, True)  # attachments, quote review and web/reference research before the draft (M13 T8)
    except Exception as exc:
        log.warning("pipeline.prepare_failed", error_type=type(exc).__name__, message_id=message_id)
    try:
        person_memory_step(message_id)  # before the draft, which reads it; a provider outage never blocks the draft
    except Exception as exc:
        log.warning("pipeline.person_memory_failed", error_type=type(exc).__name__, message_id=message_id)
    proposed = propose_step(message_id)
    for approval_id in proposed["approval_ids"]:
        send_card_step(company_id, approval_id)
    if proposed["exceptions"]:
        alert_exceptions_step(company_id, message_id)


def _after_understanding(message_id: str, final_failure: bool, history: bool = False) -> bool:
    resolve_step(message_id)
    case_id = link_step(message_id)
    company_id = company_step(message_id)
    if case_id is None or company_id is None:
        return False
    if history:
        _index(message_id)
        for sent_id in link_sent_history_step(message_id, case_id):
            _index(sent_id)
        try:
            prepare_step(message_id, False)  # history reads attachments and reviews quotes, never researches
        except Exception as exc:
            log.warning("pipeline.prepare_failed", error_type=type(exc).__name__, message_id=message_id)
    else:
        _live(company_id, message_id, final_failure)
    for attachment_id in attachments_step(message_id):  # #9: file after linking (needs the case context)
        enqueue_filing(company_id, attachment_id)
    if not history:  # the pre-draft review has no retries; the queued one does, and replays a stored review
        quote_after_understanding(company_id, message_id)
    return True


@DBOS.workflow(name=PIPELINE_ENTRY)
def pipeline_entry(message_id: str) -> str:
    """Orchestrator (#1): understand → resolve sender → link → propose + rules → ask owner. One step per stage.

    Reloaded history (M13) runs the same stages without the proposal and without any message to Harjot.
    A failed understanding with attempts left stops here (the hourly requeue retries it); the final failure still
    opens an `other` case and tells Harjot. Any stage that outlives its retries marks the message for the requeue.
    """
    try:
        history = history_step(message_id)
        status = understand_step(message_id)
        if status == "budget":
            company_id = company_step(message_id)
            if company_id is not None and not history:
                alert_budget_step(company_id)
            return "blocked"
        if status == "failed":
            if not final_failure_step(message_id):
                return "failed"
            status = "final"
        linked = _after_understanding(message_id, final_failure=status == "final", history=history)
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


@DBOS.step(name="pipeline.history_partitions")
def history_partitions_step(message_ids: list[str]) -> dict[str, str]:
    found = history_partitions(get_engine(), [_as_uuid(m) for m in message_ids])
    return {str(message_id): partition for message_id, partition in found.items()}


@DBOS.workflow(name="pipeline.requeue")
def requeue_failed(scheduled_time: datetime, context: Any) -> None:
    """Hourly: rerun failed pipeline runs (max 3 attempts per message) and messages stranded in `pending`. Reloaded
    history stays on the history queue, behind its sender's earlier mail."""
    candidates = requeue_candidates_step(scheduled_time.astimezone(UTC).isoformat())
    if not candidates:
        return
    partitions = history_partitions_step([message_id for message_id, _ in candidates])
    for message_id, workflow_id in candidates:
        partition = partitions.get(message_id)
        if partition is not None:
            with SetWorkflowID(workflow_id), SetEnqueueOptions(queue_partition_key=partition):
                queues.history_queue().enqueue(pipeline_entry, message_id)
        else:
            with SetWorkflowID(workflow_id):
                queues.pipeline_queue().enqueue(pipeline_entry, message_id)
