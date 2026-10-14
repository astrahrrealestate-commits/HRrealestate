"""Understand message stage: runs the understanding agent and records UnderstandingRow."""

from datetime import datetime, timedelta
from uuid import UUID

from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from app.contracts import Direction, Suspicious
from app.core.errors import AgentFailedError, BudgetExceededError
from app.core.logging import get_logger
from app.core.settings import Settings
from app.db.enums import PipelineStatus
from app.db.models import AttachmentRow, MessageRow, OwnerAccount, UnderstandingRow
from app.llm.agents.understanding import UNDERSTANDING, understanding_prompt
from app.llm.calls import CallContext, run_agent
from app.llm.render import AttachmentMeta
from app.pipeline.injection_scan import scan

log = get_logger(__name__)


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
        scan_reason = scan(f"{subject or ''}\n{msg.text}")
        prompt_text = understanding_prompt(
            text=msg.text,
            channel=msg.channel,
            subject=subject,
            attachments=att_metas,
        )
        company_id = msg.company_id
        wordless_with_files = not msg.text.strip() and bool(attachments)

    try:
        ctx = CallContext(company_id=company_id, purpose="triage")
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

    except BudgetExceededError:  # wait, do not fail: the message stays pending for the hourly sweep
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
                MessageRow.created_at > now - STALE_PENDING_UNTIL,
                ~owner.exists(),
            )
        ).all()
    hour = f"{now:%Y%m%d%H}"
    return [(mid, f"pipe:{mid}:r{n}:{hour}") for mid, n in failed] + [(mid, f"pipe:{mid}:p{hour}") for mid in stranded]


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
