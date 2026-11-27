"""Reload one mailbox in history mode (M13 T2), after `mail_purge`. Run by `mail_reload_cli`; every step may run again.

`reingest` records the mail of the last days as raw events marked as history; the worker fetches and stores each one and
leaves it `held`. `run_history` puts the held mail on the history queue, oldest first, one sender's mail in order.
`settle_history` resolves the reloaded cases nobody has written on for a while.
"""

from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import ColumnElement, Engine, func, select
from sqlalchemy.orm import Session

from app.contracts import CaseState, Channel, Direction
from app.core.errors import EstateOSError
from app.core.logging import get_logger
from app.core.settings import Settings
from app.core.workflow_names import (
    HISTORY_QUEUE,
    PIPELINE_ENTRY,
    history_ingest_partition,
    history_partition,
    pipeline_workflow_id,
)
from app.db.enums import PipelineStatus, WaitStatus
from app.db.models import Case, CaseLink, MessageIndexState, MessageRow, WaitRow
from app.ingestion.gmail_sync import _listing
from app.ingestion.process import IngestDeps
from app.ingestion.repository import Enqueuer, record_event, resolve_channel_account
from app.pipeline import case_repo
from app.pipeline.understand import MAX_PIPELINE_ATTEMPTS
from app.tools.message_rag.indexer import index_message
from app.workflows.mail_purge_scope import mailbox_company, of_mailbox

log = get_logger(__name__)
RECORD_BATCH = 100  # raw events per transaction
IDLE_DAYS = 14
RELOAD_ACTOR = "reload"


def reingest(deps: IngestDeps, mailbox: str, *, days: int) -> int:
    """Record one history raw event per mail of the last `days` days (sent mail included; spam, trash and drafts are
    ignored when they are read). Mail already recorded is skipped. Returns the number newly recorded."""
    with Session(deps.engine, expire_on_commit=False) as session:
        account = resolve_channel_account(session, Channel.gmail, mailbox.strip().lower())
    listed = _listing(deps.gmail_mailbox(account.address), timedelta(days=days)).ids
    oldest_first = list(reversed(listed))  # Gmail lists the newest first
    base = {"v": 1, "kind": "gmail", "mailbox": account.address, "history": True}
    recorded = 0
    for start in range(0, len(oldest_first), RECORD_BATCH):
        with Session(deps.engine) as session, session.begin():
            for offset, message_id in enumerate(oldest_first[start : start + RECORD_BATCH]):
                raw_id = record_event(
                    session, deps.enqueuer, account, message_id, {**base, "message_id": message_id},
                    queue=HISTORY_QUEUE, partition_key=history_ingest_partition(start + offset),
                )  # fmt: skip
                recorded += raw_id is not None
    log.info("mail_reload.reingest", company_id=str(account.company_id), listed=len(listed), recorded=recorded)
    return recorded


def _held(engine: Engine, mailbox: str) -> list[tuple[UUID, str]]:
    with Session(engine) as session:
        rows = session.execute(
            select(MessageRow.id, MessageRow.sender_identity)
            .where(
                of_mailbox(mailbox_company(session, mailbox), mailbox),
                MessageRow.pipeline_status == PipelineStatus.held,
            )
            .order_by(MessageRow.sent_at, MessageRow.id)
        ).all()
    return [(row.id, row.sender_identity) for row in rows]


def run_history(engine: Engine, enqueuer: Enqueuer, mailbox: str) -> int:
    """Enqueue every held message, oldest first. Each is released and enqueued in one transaction of its own: DBOS
    orders a partition by the enqueueing transaction's time, and a stop half way leaves the rest held for a rerun."""
    released = 0
    for message_id, sender in _held(engine, mailbox):
        with Session(engine) as session, session.begin():
            row = session.scalar(select(MessageRow).where(MessageRow.id == message_id).with_for_update())
            if row is None or row.pipeline_status is not PipelineStatus.held:
                continue
            row.pipeline_status = PipelineStatus.pending  # from here the hourly requeue looks after it
            options = {
                "queue_name": HISTORY_QUEUE,
                "workflow_name": PIPELINE_ENTRY,
                "workflow_id": pipeline_workflow_id(message_id),
                "queue_partition_key": history_partition(row.company_id, sender),
            }
            enqueuer.enqueue_in_transaction(session, options, str(message_id))
            released += 1
    log.info("mail_reload.run_history", released=released)
    return released


def _idle_cases(session: Session, company_id: UUID, mailbox: str, cutoff: datetime) -> list[UUID]:
    """Open cases that hold reloaded mail of this mailbox, whose newest message (any channel, either direction) is older
    than `cutoff` and on which nobody owes an answer."""
    reloaded = (
        select(CaseLink.case_id)
        .join(MessageRow, MessageRow.id == CaseLink.message_id)
        .where(CaseLink.company_id == company_id, of_mailbox(company_id, mailbox),
               MessageRow.meta["history"].as_boolean().is_(True))
    )  # fmt: skip
    newest = (
        select(CaseLink.case_id, func.max(MessageRow.sent_at).label("last_at"))
        .join(MessageRow, (MessageRow.id == CaseLink.message_id) & (MessageRow.company_id == company_id))
        .where(CaseLink.company_id == company_id)
        .group_by(CaseLink.case_id)
        .subquery()
    )
    waiting = select(WaitRow.id).where(
        WaitRow.company_id == company_id, WaitRow.case_id == Case.id, WaitRow.status == WaitStatus.waiting
    )
    return list(
        session.scalars(
            select(Case.id)
            .join(newest, newest.c.case_id == Case.id)
            .where(
                Case.company_id == company_id,
                Case.state.in_(case_repo.OPEN_STATES),
                Case.id.in_(reloaded),
                newest.c.last_at < cutoff,
                ~waiting.exists(),
            )
            .order_by(Case.id)
        )
    )


class HistoryNotDoneError(EstateOSError):
    """Reloaded mail is still on its way through the pipeline: settling or drafting now could resolve or answer a case
    whose newer mail has not been read yet."""


def _history_of(company_id: UUID, mailbox: str) -> list[ColumnElement[bool]]:
    return [
        of_mailbox(company_id, mailbox),
        MessageRow.direction == Direction.inbound,
        MessageRow.meta["history"].as_boolean().is_(True),
    ]


def _unprocessed(session: Session, company_id: UUID, mailbox: str) -> int:
    """Reloaded inbound mail the pipeline has not finished: held, pending, or failed with a retry still to come."""
    retrying = (MessageRow.pipeline_status == PipelineStatus.failed) & (
        MessageRow.pipeline_attempts < MAX_PIPELINE_ATTEMPTS
    )
    waiting = MessageRow.pipeline_status.in_([PipelineStatus.held, PipelineStatus.pending]) | retrying
    query = select(func.count()).where(*_history_of(company_id, mailbox), waiting)
    return int(session.scalar(query) or 0)


def require_history_done(session: Session, company_id: UUID, mailbox: str) -> None:
    """`HistoryNotDoneError` while `run-history` is still working through the reloaded mail."""
    waiting = _unprocessed(session, company_id, mailbox)
    if waiting:
        raise HistoryNotDoneError(
            f"{waiting} reloaded messages are not processed yet; wait for run-history to finish (see --status) "
            "or pass --force"
        )


def history_status(engine: Engine, mailbox: str) -> dict[str, int]:
    """How far the overnight run is: the reloaded inbound mail by pipeline state."""
    states = (PipelineStatus.held, PipelineStatus.pending, PipelineStatus.failed, PipelineStatus.done)
    with Session(engine) as session:
        company_id = mailbox_company(session, mailbox)
        rows = session.execute(
            select(MessageRow.pipeline_status, func.count())
            .where(*_history_of(company_id, mailbox))
            .group_by(MessageRow.pipeline_status)
        ).all()
    counts = {status: int(n) for status, n in rows}
    return {state.value: counts.get(state, 0) for state in states}


def settle_history(engine: Engine, mailbox: str, *, idle_days: int = IDLE_DAYS, force: bool = False) -> int:
    """Resolve the reloaded cases quiet for `idle_days` (they reopen on new mail as usual). Returns how many. Refuses
    while reloaded mail is unprocessed (`HistoryNotDoneError`) unless `force`."""
    cutoff = datetime.now(UTC) - timedelta(days=idle_days)
    with Session(engine) as session, session.begin():
        company_id = mailbox_company(session, mailbox)
        if force:
            log.warning("mail_reload.settle_forced", unprocessed=_unprocessed(session, company_id, mailbox))
        else:
            require_history_done(session, company_id, mailbox)
        cases = _idle_cases(session, company_id, mailbox, cutoff)
        for case_id in cases:
            case_repo.transition(session, company_id, case_id, CaseState.resolved, actor=RELOAD_ACTOR)
    log.info("mail_reload.settled", company_id=str(company_id), cases=len(cases))
    return len(cases)


def _sent_only(session: Session, company_id: UUID, mailbox: str) -> list[UUID]:
    """Reloaded sent mail in a thread without inbound mail and not yet in the index: no history run reaches it."""
    inbound = select(MessageRow.thread_ref).where(
        MessageRow.company_id == company_id, MessageRow.direction == Direction.inbound,
        MessageRow.thread_ref.is_not(None),
    )  # fmt: skip
    indexed = select(MessageIndexState.message_id).where(MessageIndexState.company_id == company_id)
    query = (
        select(MessageRow.id)
        .where(
            of_mailbox(company_id, mailbox),
            MessageRow.direction == Direction.outbound,
            MessageRow.meta["history"].as_boolean().is_(True),
            MessageRow.thread_ref.not_in(inbound),
            MessageRow.id.not_in(indexed),
        )
        .order_by(MessageRow.sent_at, MessageRow.id)
    )
    return list(session.scalars(query).all())


def index_sent_history(engine: Engine, settings: Settings, mailbox: str) -> int:
    """Index Harjot's reloaded mail in threads that hold only his mail, so Astra can find what he wrote there.
    Returns how many were indexed; a rerun picks up only what is still missing."""
    with Session(engine) as session:
        company_id = mailbox_company(session, mailbox)
        pending = _sent_only(session, company_id, mailbox)
    done = sum(index_message(engine, settings, message_id) == "indexed" for message_id in pending)
    log.info("mail_reload.sent_history_indexed", company_id=str(company_id), indexed=done, seen=len(pending))
    return done
