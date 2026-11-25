"""Store an inbound WhatsApp message in the webhook's own transaction, before any queue slot or pipeline stage.

Chats shows every WhatsApp message the owner receives, so the row must exist the moment the provider is answered. The
worker (`app.ingestion.process`) still runs for every event: it downloads media, resolves the sender and routes the
message to the case pipeline, and its `save_message` completes this row instead of inserting a second one.

Pure normalisation plus one idempotent insert and one directory lookup: no network, no model call, nothing that can
wait. The lookup also decides whether the message may ever enter the case pipeline (`skipped` = Chats only).
"""

from typing import Any
from uuid import UUID

from sqlalchemy.orm import Session

from app.channels.whatsapp.inbound import WaInbound, event_from_payload
from app.channels.whatsapp.normalise import to_message
from app.contracts import Channel
from app.db.enums import PipelineStatus
from app.db.known_contacts import feeds_pipeline
from app.db.models import ChannelAccount, MessageRow
from app.ingestion.repository import save_message


def store_inbound(
    session: Session, account: ChannelAccount, raw_event_id: UUID, payload: dict[str, Any]
) -> UUID | None:
    """The message row for a stored raw-event `payload` (created once per company), or None when the payload is not an
    inbound message. Parses the cleaned payload, the very input the worker re-parses, so both write the same row.
    Raises `UnroutableMessageError` for a sender without a usable phone number: the worker records that as failed."""
    event = event_from_payload(payload)
    if not isinstance(event, WaInbound):
        return None
    message, meta = to_message(event, company_id=account.company_id, raw_event_id=raw_event_id)
    message_id, created = save_message(session, message, meta, [])
    if created and not feeds_pipeline(session, account.company_id, Channel.whatsapp, message.sender_identity):
        row = session.get(MessageRow, message_id)
        if row is not None:
            row.pipeline_status = PipelineStatus.skipped  # Chats only: decided once, here; the worker honours it
    return message_id
