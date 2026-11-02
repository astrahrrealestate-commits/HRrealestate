"""Ingestion workflows: thin, deterministic DBOS shells around app.ingestion.process (all I/O lives in steps)."""

from dataclasses import asdict
from datetime import datetime
from typing import Any
from uuid import UUID

from dbos import DBOS, SetWorkflowID
from sqlalchemy.orm import Session

from app.core.logging import get_logger
from app.core.workflow_names import GMAIL_SYNC, PROCESS_EVENT
from app.ingestion import gmail_sync as mailbox_sync
from app.ingestion import process
from app.pipeline import case_repo
from app.workflows import owner_reply, pipeline, queues
from app.workflows.deps import get_deps

log = get_logger(__name__)

# 8 attempts at 5s doubling: ~10 minutes of provider/DB hiccups ride out inside one run; longer outages are
# recorded as `requeue:` failures and picked up by the hourly requeue sweep.
_RETRY: dict[str, Any] = {
    "retries_allowed": True,
    "max_attempts": 8,
    "interval_seconds": 5.0,
    "backoff_rate": 2.0,
    "should_retry": process.is_transient,
}


@DBOS.step(name="ingest.persist_event", **_RETRY)
def persist_step(raw_event_id: str) -> dict[str, Any]:
    persisted = process.persist_event(get_deps(), UUID(raw_event_id))
    if persisted.message_id and persisted.route == "none":  # outbound mail: thread it onto its case (idempotent)
        with Session(get_deps().engine) as session, session.begin():
            case_repo.link_outbound_reply(session, UUID(persisted.message_id))
    return asdict(persisted)


@DBOS.step(name="ingest.mark_failed")
def mark_failed_step(raw_event_id: str, error: str) -> None:
    process.mark_requeueable(get_deps(), UUID(raw_event_id), error)


@DBOS.workflow(name=PROCESS_EVENT)
def process_event(raw_event_id: str) -> str:
    try:
        result = persist_step(raw_event_id)
    except (
        Exception
    ) as exc:  # outlived its retries, or a bug: record it for the requeue sweep, then let DBOS mark ERROR
        mark_failed_step(raw_event_id, f"{type(exc).__name__}: {str(exc)[:300]}")
        raise
    message_id, route = result["message_id"], result["route"]
    if message_id and route in ("owner", "pipeline"):
        target, prefix = (owner_reply.owner_reply, "owner") if route == "owner" else (pipeline.pipeline_entry, "pipe")
        with SetWorkflowID(f"{prefix}:{message_id}"):  # one routing per message, even if replayed or requeued
            queues.pipeline_queue().enqueue(target, message_id)
    return str(result["outcome"])


@DBOS.step(name="ingest.requeue_candidates")
def requeue_candidates_step() -> list[tuple[str, str]]:
    """Events with any run still waiting in the queue (the original or an earlier rerun, during a worker backlog)
    are skipped: another rerun would only repeat the Gmail fetch / media download before that one gets there."""
    candidates = process.requeue_candidates(get_deps())
    if not candidates:
        return []
    queued = {w.workflow_id.split(":")[1] for w in DBOS.list_workflows(workflow_id_prefix="evt:", status="ENQUEUED")}
    return [(str(raw_id), wf) for raw_id, wf in candidates if str(raw_id) not in queued]


@DBOS.workflow(name="ingest.requeue")
def requeue_failed(scheduled_time: datetime, context: Any) -> None:
    """Hourly: rerun raw events that failed retryably or are stranded in `pending`. Ids carry the attempt (or the
    hour), so a sweep that runs twice enqueues each event once, and failures rerun at most MAX_REQUEUES times."""
    for raw_event_id, workflow_id in requeue_candidates_step():
        with SetWorkflowID(workflow_id):
            queues.pipeline_queue().enqueue(process_event, raw_event_id)


@DBOS.step(name="ingest.sync_mailbox", **_RETRY)
def sync_step(account_id: str, push_history_id: int) -> int:
    return mailbox_sync.sync_mailbox(get_deps(), UUID(account_id), push_history_id)


@DBOS.workflow(name=GMAIL_SYNC)
def gmail_sync(account_id: str, push_history_id: int) -> int:
    return sync_step(account_id, push_history_id)


@DBOS.step(name="gmail.accounts")
def accounts_step() -> list[tuple[str, str, str]]:
    return [(str(a), addr, str(c)) for a, addr, c in mailbox_sync.gmail_accounts(get_deps())]


@DBOS.step(name="gmail.renew_watch", **_RETRY)
def renew_step(account_id: str, address: str, company_id: str) -> str:
    return mailbox_sync.renew_watch(get_deps(), UUID(account_id), address, UUID(company_id)).isoformat()


@DBOS.workflow(name="gmail.watch_renew")
def gmail_watch_renew(scheduled_time: datetime, context: Any) -> None:
    for account_id, address, company_id in accounts_step():
        try:  # one broken mailbox (revoked consent, deleted account) must not block the others
            renew_step(account_id, address, company_id)
        except Exception as exc:  # DBOS cancellation is a BaseException: it still stops the workflow
            log.error("gmail.watch_renew_failed", account_id=account_id, error=type(exc).__name__)


@DBOS.step(name="gmail.current_history", **_RETRY)
def current_history_step(address: str) -> int:
    return get_deps().gmail_mailbox(address).current_history_id()


@DBOS.workflow(name="gmail.backfill")
def gmail_backfill(scheduled_time: datetime, context: Any) -> None:
    """Hourly safety net for lost pushes: sync every mailbox up to its current history id."""
    for account_id, address, _company in accounts_step():
        try:
            history = current_history_step(address)
        except Exception as exc:
            log.error("gmail.backfill_failed", account_id=account_id, error=type(exc).__name__)
            continue
        with SetWorkflowID(backfill_workflow_id(account_id, scheduled_time)):
            queues.gmail_sync_queue().enqueue(gmail_sync, account_id, history)


def backfill_workflow_id(account_id: str, scheduled_time: datetime) -> str:
    return f"gbackfill:{account_id}:{scheduled_time:%Y%m%d%H}"
