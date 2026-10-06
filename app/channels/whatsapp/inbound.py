"""WhatsApp inbound: webhook verification, parsing into typed events, normalisation to `Message`.

Provider-neutral: Meta Cloud API and 360dialog deliver the same webhook body. Parsing never raises on provider data:
garbage yields no events, unknown message types become `kind="unsupported"`, malformed items are skipped and logged.
"""

import json
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ValidationError

from app.channels.whatsapp.webhook_auth import MAX_WEBHOOK_BYTES
from app.channels.whatsapp.webhook_models import (
    Change,
    Contact,
    Entry,
    Media,
    RawEcho,
    RawMessage,
    RawStatus,
    StatusError,
    Value,
    Webhook,
)
from app.contracts import Channel, Direction, Message, normalise_identity
from app.core.errors import UnroutableMessageError, WebhookTooLargeError
from app.core.logging import get_logger

log = get_logger(__name__)

_MEDIA_KINDS = ("image", "document", "audio", "video", "sticker")


@dataclass(frozen=True)
class WaMediaRef:
    id: str
    mime_type: str | None
    sha256: str | None
    filename: str | None


@dataclass(frozen=True)
class WaInbound:
    kind: str
    wamid: str
    sender: str | None  # None for senders without a phone id (e.g. username-only users)
    phone_number_id: str
    sent_at: datetime
    text: str
    contact_name: str | None = None
    media: WaMediaRef | None = None
    interactive_id: str | None = None
    reply_to: str | None = None
    new_wa_id: str | None = None  # system message: user changed number (M3 identity update)
    raw: dict[str, Any] = field(default_factory=dict, compare=False)


@dataclass(frozen=True)
class WaStatus:
    wamid: str
    status: str
    phone_number_id: str
    recipient: str | None
    at: datetime
    error_codes: list[int] = field(default_factory=list)
    raw: dict[str, Any] = field(default_factory=dict, compare=False)


@dataclass(frozen=True)
class WaEcho:
    kind: str
    wamid: str
    business_number: str
    recipient: str
    phone_number_id: str
    sent_at: datetime
    text: str
    media: WaMediaRef | None = None
    raw: dict[str, Any] = field(default_factory=dict, compare=False)


WaEvent = WaInbound | WaStatus | WaEcho


# ---- parsing -----------------------------------------------------------------------------------------------------

_MESSAGE_FIELDS: dict[str, frozenset[str]] = {
    "messages": frozenset({"messages", "statuses"}),
    "smb_message_echoes": frozenset({"message_echoes"}),
}


def parse_webhook(body: bytes) -> list[WaEvent]:
    """Typed events from a verified webhook body. Raises only `WebhookTooLargeError`; never on provider data."""
    if len(body) > MAX_WEBHOOK_BYTES:
        raise WebhookTooLargeError(f"webhook body {len(body)} bytes exceeds {MAX_WEBHOOK_BYTES}")
    try:
        webhook = Webhook.model_validate(json.loads(body))
    except (ValueError, ValidationError, RecursionError):
        log.warning("whatsapp.webhook.unparseable", size=len(body))
        return []
    if webhook.object != "whatsapp_business_account":
        return []
    events: list[WaEvent] = []
    for raw_entry in webhook.entry:
        entry = _validate(Entry, raw_entry)
        for raw_change in entry.changes if entry else []:
            change = _validate(Change, raw_change)
            if change is not None:
                events.extend(_parse_change(change))
    return events


def _parse_change(change: Change) -> list[WaEvent]:
    lists = _MESSAGE_FIELDS.get(change.field)
    if lists is None:
        log.info("whatsapp.webhook.ignored_field", field=change.field)
        return []
    value = _validate(Value, change.value)
    if value is None:
        return []
    pnid = value.metadata.phone_number_id
    contacts = [c for c in (_validate(Contact, raw) for raw in value.contacts) if c and c.wa_id]
    names = {c.wa_id: c.profile.name for c in contacts if c.profile}
    events: list[WaEvent] = []
    for raw in value.messages if "messages" in lists else []:
        if (msg := _validate(RawMessage, raw)) is not None:
            events.append(_inbound(msg, pnid, names.get(msg.sender or ""), raw))
    for raw in value.message_echoes if "message_echoes" in lists else []:
        if (echo := _validate(RawEcho, raw)) is not None:
            events.append(_echo(echo, pnid, raw))
    for raw in value.statuses if "statuses" in lists else []:
        if (status := _validate(RawStatus, raw)) is not None:
            events.append(_status(status, pnid, raw))
    return events


def _validate[M: BaseModel](model: type[M], item: Any) -> M | None:
    if not isinstance(item, dict):
        log.warning("whatsapp.webhook.non_object_item", model=model.__name__, item_type=type(item).__name__)
        return None
    try:
        return model.model_validate(item)
    except ValidationError as exc:
        log.warning(
            "whatsapp.webhook.bad_item",
            model=model.__name__,
            item_id=str(item.get("id", ""))[:80],
            errors=[".".join(map(str, e["loc"])) for e in exc.errors()][:5],
        )
        return None


def _media(msg: RawMessage) -> Media | None:
    for kind in _MEDIA_KINDS:
        media: Media | None = getattr(msg, kind)
        if media is not None and media.id:
            return media
    return None


def _render(msg: RawMessage) -> tuple[str, str, str | None]:
    """(kind, human-readable text, reply id) for any message type, never raising."""
    if msg.type == "text" and msg.text and msg.text.body:
        return "text", msg.text.body, None
    if msg.type in _MEDIA_KINDS and (media := _media(msg)):
        return msg.type, media.caption or f"[{msg.type}]", None
    if msg.type == "interactive" and msg.interactive:
        reply = msg.interactive.button_reply or msg.interactive.list_reply
        if reply and reply.id:
            return "interactive", reply.title, reply.id
    if msg.type == "button" and msg.button and msg.button.payload:
        return "button", msg.button.text or "", msg.button.payload
    if msg.type == "reaction" and msg.reaction:
        return "reaction", f"Reaction {msg.reaction.emoji or ''} to {msg.reaction.message_id or '?'}", None
    if msg.type == "location" and msg.location:
        loc = msg.location
        parts = [p for p in (loc.name, loc.address) if p]
        return "location", f"Location: {', '.join(parts)} ({loc.latitude}, {loc.longitude})", None
    if msg.type == "system" and msg.system:
        return "system", msg.system.body or "[system message]", None
    if msg.type == "contacts" and msg.contacts:
        names = [c.name.formatted_name for c in msg.contacts if c.name and c.name.formatted_name]
        return "contacts", "Contact card: " + (", ".join(names) or "?"), None
    return "unsupported", "[unsupported message]", None


def _media_ref(msg: RawMessage) -> WaMediaRef | None:
    media = _media(msg)
    if media is None or media.id is None:
        return None
    return WaMediaRef(id=media.id, mime_type=media.mime_type, sha256=media.sha256, filename=media.filename)


def _inbound(msg: RawMessage, pnid: str, contact_name: str | None, raw: dict[str, Any]) -> WaInbound:
    kind, text, interactive_id = _render(msg)
    return WaInbound(
        kind=kind,
        wamid=msg.id,
        sender=msg.sender,
        phone_number_id=pnid,
        sent_at=msg.timestamp,
        text=text,
        contact_name=contact_name,
        media=_media_ref(msg),
        interactive_id=interactive_id,
        reply_to=msg.context.id if msg.context else None,
        new_wa_id=msg.system.new_wa_id if msg.system else None,
        raw=raw,
    )


def _echo(msg: RawEcho, pnid: str, raw: dict[str, Any]) -> WaEcho:
    kind, text, _ = _render(msg)
    return WaEcho(
        kind=kind,
        wamid=msg.id,
        business_number=msg.sender or "",
        recipient=msg.to,
        phone_number_id=pnid,
        sent_at=msg.timestamp,
        text=text,
        media=_media_ref(msg),
        raw=raw,
    )


def _status(status: RawStatus, pnid: str, raw: dict[str, Any]) -> WaStatus:
    return WaStatus(
        wamid=status.id,
        status=status.status.value,
        phone_number_id=pnid,
        recipient=status.recipient_id,
        at=status.timestamp,
        error_codes=[e.code for e in (_validate(StatusError, x) for x in status.errors) if e and e.code is not None],
        raw=raw,
    )


# ---- normalisation -----------------------------------------------------------------------------------------------


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
