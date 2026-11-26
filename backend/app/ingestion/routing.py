"""Where a stored message goes next: the owner's command handler, the case pipeline, or nowhere."""

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.contracts import Channel, Direction, Message
from app.db.enums import PipelineStatus
from app.db.known_contacts import feeds_pipeline, is_known_contact
from app.db.models import MessageRow, OwnerAccount


def route_message(session: Session, message: Message, message_id: UUID) -> str:
    """Owner commands come only over WhatsApp and Google Chat, where the sender id is provider-verified.
    An email From: header is trivially spoofable, so Gmail never routes to the owner handler in Phase 1.
    WhatsApp from a number the directory does not know stays in Chats and never reaches the pipeline (ADR 0015)."""
    if message.direction is Direction.outbound:
        if message.channel is Channel.whatsapp:
            _skip_echo_to_stranger(session, message, message_id)
        return "none"
    if message.channel is Channel.google_chat:
        owner = session.scalar(
            select(OwnerAccount.id).where(
                OwnerAccount.company_id == message.company_id,
                OwnerAccount.chat_user == message.sender_identity,
            )
        )
        return "owner" if owner is not None else "none"
    if message.channel is not Channel.whatsapp:
        return "pipeline"
    owner = session.scalar(
        select(OwnerAccount.id).where(
            OwnerAccount.company_id == message.company_id, OwnerAccount.whatsapp_e164 == message.sender_identity
        )
    )
    if owner is not None:
        return "owner"
    return "pipeline" if _is_pipeline_contact(session, message, message_id) else "none"


def _skip_echo_to_stranger(session: Session, message: Message, message_id: UUID) -> None:
    """A reply Harjot typed on his phone to a chat-only chat stays out of the case world with that chat."""
    row = session.get(MessageRow, message_id)
    if row is None or row.pipeline_status is not PipelineStatus.pending or message.thread_ref is None:
        return
    if not feeds_pipeline(session, message.company_id, message.channel, message.thread_ref):
        row.pipeline_status = PipelineStatus.skipped


def _is_pipeline_contact(session: Session, message: Message, message_id: UUID) -> bool:
    """The webhook decided once and marked the row `skipped`; a row the worker created itself is decided here."""
    row = session.get(MessageRow, message_id)
    if row is None or row.pipeline_status is PipelineStatus.skipped:
        return False
    if row.pipeline_status is not PipelineStatus.pending:  # a replay after the pipeline already ran
        return True
    if is_known_contact(session, message.company_id, message.channel, message.sender_identity):
        return True
    row.pipeline_status = PipelineStatus.skipped
    return False
