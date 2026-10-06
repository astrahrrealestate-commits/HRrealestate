"""Simulator payloads must pass through the same parsers and verifiers as real provider deliveries."""

from datetime import UTC, datetime

from app.channels.gmail.mime import parse_email
from app.channels.gmail.push import parse_push_body
from app.channels.whatsapp.inbound import WaInbound, parse_webhook
from app.dev import fixtures as fx

AT = datetime(2026, 10, 6, 9, 30, tzinfo=UTC)
TENANT = "+4915550000001"


def _one(body: bytes) -> WaInbound:
    [event] = parse_webhook(body)
    assert isinstance(event, WaInbound)
    return event


def test_whatsapp_text() -> None:
    message = fx.wa_text("wamid.A", "Hallo", AT)
    event = _one(fx.wa_webhook(pnid=fx.DEV_PNID, sender_e164=TENANT, name="Tenant", message=message))
    assert (event.kind, event.wamid, event.text, event.sent_at) == ("text", "wamid.A", "Hallo", AT)
    assert (event.sender, event.phone_number_id, event.contact_name) == ("4915550000001", fx.DEV_PNID, "Tenant")


def test_whatsapp_image_carries_media_ref_and_caption() -> None:
    message = fx.wa_image("wamid.B", "MEDIA_1", "a" * 64, "Foto", AT)
    event = _one(fx.wa_webhook(pnid=fx.DEV_PNID, sender_e164=TENANT, name="Tenant", message=message))
    assert event.media is not None
    assert (event.kind, event.media.id, event.text) == ("image", "MEDIA_1", "Foto")


def test_whatsapp_button_reply() -> None:
    message = fx.wa_button("wamid.C", "apr:01900000-0000-7000-8000-0000000000cc:ok", "Freigeben", AT, "wamid.OUT1")
    event = _one(fx.wa_webhook(pnid=fx.DEV_PNID, sender_e164=fx.DEV_OWNER_E164, name="Harjot", message=message))
    assert (event.interactive_id, event.reply_to) == ("apr:01900000-0000-7000-8000-0000000000cc:ok", "wamid.OUT1")


def test_email_with_attachment_and_reply_headers() -> None:
    raw = fx.email_bytes(
        sender="Tenant 001 <tenant-001@example.test>",
        subject="Re: Heizung",
        body="Foto anbei",
        message_id="<b@example.test>",
        at=AT,
        in_reply_to="<a@example.test>",
        attachment=fx.Attachment("foto.jpg", "image/jpeg", b"\xff\xd8jpeg"),
    )
    parsed = parse_email(raw)
    assert (parsed.from_addr, parsed.text.strip(), parsed.in_reply_to) == (
        "tenant-001@example.test",
        "Foto anbei",
        "<a@example.test>",
    )
    [att] = parsed.attachments
    assert (att.filename, att.mime_type, att.data) == ("foto.jpg", "image/jpeg", b"\xff\xd8jpeg")


def test_pubsub_envelope() -> None:
    notice = parse_push_body(fx.pubsub_envelope(fx.DEV_MAILBOX, 42, "pubsub-1"))
    assert (notice.email, notice.history_id, notice.message_id) == (fx.DEV_MAILBOX, 42, "pubsub-1")
