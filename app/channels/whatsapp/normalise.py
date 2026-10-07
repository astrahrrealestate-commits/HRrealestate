"""WhatsApp events to `Message` + row metadata: E.164 senders; echoes are outbound, threaded on the customer."""

from typing import Any
from uuid import UUID

from app.channels.whatsapp.inbound import WaEcho, WaInbound
from app.contracts import Channel, Direction, Message, normalise_identity
from app.core.errors import UnroutableMessageError


def _wa_identity(raw: str | None, wamid: str) -> str:
    """E.164 for a WhatsApp id (contract accepts well-formed numbers phonenumbers does not know yet).
    No usable id → `UnroutableMessageError` (the raw event is kept, never retried)."""
    if raw:
        try:
            return normalise_identity(raw)
        except ValueError:
            pass
    raise UnroutableMessageError(f"no routable sender for {wamid}")


def to_message(event: WaInbound | WaEcho, *, company_id: UUID, raw_event_id: UUID) -> tuple[Message, dict[str, Any]]:
    """`Message` plus row metadata. Attachments are added by ingestion after the media download.

    Raises `UnroutableMessageError` when the sender has no usable WhatsApp id.
    """
    if isinstance(event, WaEcho):
        customer = _wa_identity(event.recipient, event.wamid)
        sender, direction = _wa_identity(event.business_number, event.wamid), Direction.outbound
    else:
        customer = sender = _wa_identity(event.sender, event.wamid)
        direction = Direction.inbound
    message = Message(
        channel=Channel.whatsapp,
        provider_msg_id=event.wamid,
        thread_ref=customer,
        sender_identity=sender,
        direction=direction,
        sent_at=event.sent_at,
        text=event.text,
        raw_event_id=raw_event_id,
        company_id=company_id,
    )
    metadata: dict[str, Any] = {"type": event.kind, "phone_number_id": event.phone_number_id}
    if isinstance(event, WaEcho):
        metadata["echo"] = True
    else:
        metadata.update(
            contact_name=event.contact_name,
            interactive_id=event.interactive_id,
            reply_to=event.reply_to,
            new_wa_id=event.new_wa_id,
        )
    if event.media:
        metadata["media"] = {"id": event.media.id, "mime_type": event.media.mime_type, "filename": event.media.filename}
    return message, {k: v for k, v in metadata.items() if v is not None}
