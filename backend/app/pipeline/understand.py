"""Understand message stage: runs the understanding agent and records UnderstandingRow."""

from datetime import datetime, timedelta
from uuid import UUID

from sqlalchemy import Engine, exists, or_, select
from sqlalchemy.orm import Session

from app.context.message_origin import is_history
from app.contracts import Direction, Suspicious, Understanding
from app.core.errors import AgentFailedError, BudgetExceededError
from app.core.logging import get_logger
from app.core.settings import Settings
from app.core.workflow_names import history_partition
from app.db.enums import PipelineStatus, RawEventStatus
from app.db.models import AttachmentRow, MessageRow, OwnerAccount, RawEvent, UnderstandingRow
from app.llm.agents.understanding import (
    MAX_UNDERSTANDING_BODY_CHARS,
    UNDERSTANDING,
    sees_sender,
    sender_shown_to_model,
    understanding_prompt,
)
from app.llm.calls import CallContext, run_agent
from app.llm.render import AttachmentMeta
from app.pipeline.injection_scan import scan

log = get_logger(__name__)
BUDGET_BLOCKED = "budget"  # pipeline_error tag on a pending message waiting for the AI limit to reset


def settle_sender_role(und: Understanding, *, prompted: bool, scanner_flagged: bool) -> Understanding:
    """Keep the model's `sender_role` only if the prompt described it and nothing flagged the mail afterwards.

    Every prompt version ships the same output schema, so an older prompt's model may still fill the field with a guess.
    The injection scanner flips `suspicious` after the answer, which the contract validator never sees.
    """
    if und.sender_role is None or (prompted and not scanner_flagged):
        return und
    return und.model_copy(update={"sender_role": None})


def understand_message(engine: Engine, settings: Settings, message_id: UUID) -> UUID | None:
    """Triage an inbound message with Pydantic AI and record UnderstandingRow."""
    with Session(engine) as session:
        msg = session.scalar(select(MessageRow).where(MessageRow.id == message_id))  # id from our own enqueue
        if msg is None:
            return None
        existing = session.scalar(
            select(UnderstandingRow.id).where(
                UnderstandingRow.company_id == msg.company_id, UnderstandingRow.message_id == message_id
            )
        )
        if existing is not None:
            if msg.pipeline_status is PipelineStatus.failed:  # a rerun after a later stage failed: try again
                with Session(engine) as reset, reset.begin():
                    stale = reset.get(MessageRow, message_id)
                    if stale is not None and stale.pipeline_status is PipelineStatus.failed:
                        stale.pipeline_status, stale.pipeline_error = PipelineStatus.pending, None
            return existing

        attachments = session.scalars(
            select(AttachmentRow).where(
                AttachmentRow.company_id == msg.company_id, AttachmentRow.message_id == message_id
            )
        ).all()
        att_metas = [
            AttachmentMeta(filename=a.filename, mime_type=a.mime_type, size_bytes=a.size_bytes) for a in attachments
        ]
        subject = msg.meta.get("subject") if msg.meta else None
        clean_text = msg.text[:MAX_UNDERSTANDING_BODY_CHARS] if msg.text else ""
        scan_reason = scan(f"{subject or ''}\n{clean_text}")
        prompt_text = understanding_prompt(
            text=msg.text,
            channel=msg.channel,
            subject=subject,
            attachments=att_metas,
            sender=sender_shown_to_model(msg.channel, msg.sender_identity),
        )
        company_id = msg.company_id
        wordless_with_files = not msg.text.strip() and bool(attachments)

    try:
        ctx = CallContext(company_id=company_id, purpose="triage", message_ids=(message_id,))
        res = run_agent(engine, settings, UNDERSTANDING, prompt_text, ctx)
        understanding_data = res.output
        if wordless_with_files and not understanding_data.requires_reply:
            # a photo or file with no words (a leak, a document) is never skipped as "nothing to answer"
            understanding_data = understanding_data.model_copy(update={"requires_reply": True})
        if scan_reason is not None and not understanding_data.suspicious.flag:
            understanding_data = understanding_data.model_copy(
                update={"suspicious": Suspicious(flag=True, reason=f"scanner: {scan_reason}")}
            )
            log.warning("pipeline.understand.injection_scanner_hit", message_id=str(message_id), reason=scan_reason)
        understanding_data = settle_sender_role(
            understanding_data,
            prompted=sees_sender(UNDERSTANDING.prompt.version),
            scanner_flagged=scan_reason is not None,
        )
        model_call_id = res.model_call_id

        with Session(engine) as session, session.begin():
            row = session.scalar(
                select(UnderstandingRow).where(
                    UnderstandingRow.company_id == company_id, UnderstandingRow.message_id == message_id
                )
            )
            if row is None:
                row = UnderstandingRow(
                    company_id=company_id,
                    message_id=message_id,
                    model_call_id=model_call_id,
                    category=understanding_data.category,
                    urgency=understanding_data.urgency,
                    body=understanding_data.model_dump(mode="json"),
                    prompt_version=understanding_data.prompt_version,
                )
                session.add(row)
                session.flush()

            msg_row = session.get(MessageRow, message_id)
            if msg_row is not None and msg_row.pipeline_status is PipelineStatus.failed:  # a requeued run succeeded
                msg_row.pipeline_status, msg_row.pipeline_error = PipelineStatus.pending, None
            return row.id

    except BudgetExceededError:  # wait, do not fail: the message stays pending; the tag keeps the sweep retrying it
        with Session(engine) as session, session.begin():
            blocked = session.get(MessageRow, message_id)
            if blocked is not None:
                blocked.pipeline_error = BUDGET_BLOCKED
        raise
    except AgentFailedError as exc:
        log.warning("pipeline.understand.failed", message_id=str(message_id), error=str(exc))
        with Session(engine) as session, session.begin():
            msg_row = session.scalar(select(MessageRow).where(MessageRow.id == message_id))
            if msg_row is not None:
                msg_row.pipeline_status = PipelineStatus.failed
                msg_row.pipeline_error = str(exc)[:300]
                msg_row.pipeline_attempts = (msg_row.pipeline_attempts or 0) + 1
        return None


def mark_pipeline_done(engine: Engine, message_id: UUID) -> None:
    """Every pipeline stage ran for this message (a failed understanding keeps its `failed` mark for the requeue)."""
    with Session(engine) as session, session.begin():
        msg = session.get(MessageRow, message_id)
        if msg is not None and msg.pipeline_status is not PipelineStatus.failed:
            msg.pipeline_status, msg.pipeline_error = PipelineStatus.done, None


MAX_PIPELINE_ATTEMPTS = 3


STALE_PENDING_AFTER = timedelta(hours=1)  # beyond step retries plus queue backlog
STALE_PENDING_UNTIL = timedelta(days=7)  # older stragglers need a human


def requeue_candidates(engine: Engine, now: datetime) -> list[tuple[UUID, str]]:
    """(message id, workflow id) to rerun (system cron, all companies): failed runs with attempts left, and inbound
    tenant messages stranded in `pending` (e.g. a deploy changed the workflow code). Ids carry the attempt or the
    hour, so a sweep running twice enqueues each rerun once."""
    owner = select(OwnerAccount.id).where(
        OwnerAccount.company_id == MessageRow.company_id, OwnerAccount.whatsapp_e164 == MessageRow.sender_identity
    )
    # A WhatsApp row is stored by the webhook before the worker has downloaded its media or decided its route (owner
    # command or case pipeline): only a message whose raw event the worker finished is stranded, not merely waiting.
    worker_done = exists().where(RawEvent.id == MessageRow.raw_event_id, RawEvent.status == RawEventStatus.processed)
    with Session(engine) as session:
        failed = session.execute(
            select(MessageRow.id, MessageRow.pipeline_attempts).where(
                MessageRow.pipeline_status == PipelineStatus.failed,
                MessageRow.pipeline_attempts < MAX_PIPELINE_ATTEMPTS,
            )
        ).all()
        stranded = session.scalars(
            select(MessageRow.id).where(
                MessageRow.pipeline_status == PipelineStatus.pending,
                MessageRow.direction == Direction.inbound,
                MessageRow.created_at < now - STALE_PENDING_AFTER,
                or_(MessageRow.created_at > now - STALE_PENDING_UNTIL, MessageRow.pipeline_error == BUDGET_BLOCKED),
                ~owner.exists(),
                worker_done,
            )
        ).all()
    hour = f"{now:%Y%m%d%H}"
    return [(mid, f"pipe:{mid}:r{n}:{hour}") for mid, n in failed] + [(mid, f"pipe:{mid}:p{hour}") for mid in stranded]


def history_partitions(engine: Engine, message_ids: list[UUID]) -> dict[UUID, str]:
    """The history queue partition of each reloaded message among our own ids (live messages are absent)."""
    with Session(engine) as session:
        rows = session.scalars(select(MessageRow).where(MessageRow.id.in_(message_ids))).all()
        return {m.id: history_partition(m.company_id, m.sender_identity) for m in rows if is_history(m)}


def mark_pipeline_failed(engine: Engine, message_id: UUID, error: str) -> int:
    """A stage outlived its retries (or hit a bug): mark the message for the hourly requeue. Returns attempts."""
    with Session(engine) as session, session.begin():
        msg = session.get(MessageRow, message_id)
        if msg is None:
            return 0
        msg.pipeline_status, msg.pipeline_error = PipelineStatus.failed, error[:300]
        msg.pipeline_attempts = (msg.pipeline_attempts or 0) + 1
        return msg.pipeline_attempts


def understanding_is_final_failure(engine: Engine, message_id: UUID) -> bool:
    """The last allowed attempt failed: continue without an understanding (case `other`) and tell Harjot."""
    with Session(engine) as session:
        attempts = session.scalar(select(MessageRow.pipeline_attempts).where(MessageRow.id == message_id))
    return (attempts or 0) >= MAX_PIPELINE_ATTEMPTS
