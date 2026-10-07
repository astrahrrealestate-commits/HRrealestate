"""Understand message stage: runs the understanding agent and records UnderstandingRow."""

from uuid import UUID

from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from app.core.errors import AgentFailedError
from app.core.logging import get_logger
from app.core.settings import Settings
from app.db.enums import PipelineStatus
from app.db.models import AttachmentRow, MessageRow, UnderstandingRow
from app.llm.agents.understanding import UNDERSTANDING, understanding_prompt
from app.llm.calls import CallContext, run_agent
from app.llm.render import AttachmentMeta

log = get_logger(__name__)


def understand_message(engine: Engine, settings: Settings, message_id: UUID) -> UUID | None:
    """Triage an inbound message with Pydantic AI and record UnderstandingRow."""
    with Session(engine) as session:
        existing = session.scalar(select(UnderstandingRow.id).where(UnderstandingRow.message_id == message_id))
        if existing is not None:
            return existing

        msg = session.scalar(select(MessageRow).where(MessageRow.id == message_id))
        if msg is None:
            return None

        attachments = session.scalars(select(AttachmentRow).where(AttachmentRow.message_id == message_id)).all()
        att_metas = [
            AttachmentMeta(filename=a.filename, mime_type=a.mime_type, size_bytes=a.size_bytes) for a in attachments
        ]
        subject = msg.meta.get("subject") if msg.meta else None
        prompt_text = understanding_prompt(
            text=msg.text,
            channel=msg.channel,
            subject=subject,
            attachments=att_metas,
        )
        company_id = msg.company_id

    try:
        ctx = CallContext(company_id=company_id, purpose="triage")
        res = run_agent(engine, settings, UNDERSTANDING, prompt_text, ctx)
        understanding_data = res.output
        model_call_id = res.model_call_id

        with Session(engine) as session, session.begin():
            row = session.scalar(select(UnderstandingRow).where(UnderstandingRow.message_id == message_id))
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

            msg_row = session.scalar(select(MessageRow).where(MessageRow.id == message_id))
            if msg_row is not None:
                msg_row.pipeline_status = PipelineStatus.done
                msg_row.pipeline_error = None

            return row.id

    except AgentFailedError as exc:
        log.warning("pipeline.understand.failed", message_id=str(message_id), error=str(exc))
        with Session(engine) as session, session.begin():
            msg_row = session.scalar(select(MessageRow).where(MessageRow.id == message_id))
            if msg_row is not None:
                msg_row.pipeline_status = PipelineStatus.failed
                msg_row.pipeline_error = str(exc)[:300]
                msg_row.pipeline_attempts = (msg_row.pipeline_attempts or 0) + 1
        return None
