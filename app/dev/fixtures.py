"""Provider-shaped payloads for the simulator: WhatsApp Cloud API webhooks, RFC 5322 mail, Pub/Sub push envelopes.

Shapes mirror the recorded fixtures in tests/fixtures/recorded/ (which came from the providers' documented payloads),
so the simulator drives exactly the code paths a real delivery does.
"""

import base64
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from email.message import EmailMessage
from email.utils import format_datetime
from typing import Any

DEV_COMPANY = "EstateOS Dev Hausverwaltung"
DEV_PNID = "100000000000001"
DEV_BUSINESS_NUMBER = "4915550000999"
DEV_MAILBOX = "hausverwaltung@example.test"
DEV_OWNER_NAME = "Suryansh Tyagi"
DEV_OWNER_E164 = "+4915550000100"
DEV_OWNER_EMAIL = "tyagisurya.04@gmail.com"


@dataclass(frozen=True)
class Attachment:
    filename: str
    mime_type: str
    data: bytes


def wa_webhook(*, pnid: str, sender_e164: str, name: str, message: dict[str, Any]) -> bytes:
    """One inbound message in a Cloud API `messages` change (360dialog forwards the same body)."""
    digits = sender_e164.removeprefix("+")
    value = {
        "messaging_product": "whatsapp",
        "metadata": {"display_phone_number": DEV_BUSINESS_NUMBER, "phone_number_id": pnid},
        "contacts": [{"profile": {"name": name}, "wa_id": digits}],
        "messages": [{"from": digits, **message}],
    }
    body = {"object": "whatsapp_business_account", "entry": [{"id": "200000000000001", "changes": [_change(value)]}]}
    return json.dumps(body).encode()


def _change(value: dict[str, Any]) -> dict[str, Any]:
    return {"field": "messages", "value": value}


def _base(wamid: str, at: datetime, kind: str, reply_to: str | None) -> dict[str, Any]:
    message: dict[str, Any] = {"id": wamid, "timestamp": str(int(at.timestamp())), "type": kind}
    if reply_to:
        message["context"] = {"from": DEV_BUSINESS_NUMBER, "id": reply_to}
    return message


def wa_text(wamid: str, text: str, at: datetime, reply_to: str | None = None) -> dict[str, Any]:
    return {**_base(wamid, at, "text", reply_to), "text": {"body": text}}


def wa_image(wamid: str, media_id: str, sha256: str, caption: str | None, at: datetime) -> dict[str, Any]:
    image = {"mime_type": "image/jpeg", "sha256": sha256, "id": media_id}
    return {**_base(wamid, at, "image", None), "image": {**image, **({"caption": caption} if caption else {})}}


def wa_button(wamid: str, button_id: str, title: str, at: datetime, reply_to: str) -> dict[str, Any]:
    reply = {"type": "button_reply", "button_reply": {"id": button_id, "title": title}}
    return {**_base(wamid, at, "interactive", reply_to), "interactive": reply}


def email_bytes(
    *,
    sender: str,
    subject: str,
    body: str,
    message_id: str,
    at: datetime,
    in_reply_to: str | None = None,
    attachment: Attachment | None = None,
    to: str = DEV_MAILBOX,
) -> bytes:
    mail = EmailMessage()
    mail["From"], mail["To"], mail["Subject"] = sender, to, subject
    mail["Date"] = format_datetime(at.astimezone(UTC))
    mail["Message-ID"] = message_id
    if in_reply_to:
        mail["In-Reply-To"] = mail["References"] = in_reply_to
    mail.set_content(body)
    if attachment:
        maintype, subtype = attachment.mime_type.split("/", 1)
        mail.add_attachment(attachment.data, maintype=maintype, subtype=subtype, filename=attachment.filename)
    return mail.as_bytes()


def pubsub_envelope(mailbox: str, history_id: int, message_id: str) -> bytes:
    data = base64.b64encode(json.dumps({"emailAddress": mailbox, "historyId": history_id}).encode()).decode()
    message = {"data": data, "messageId": message_id, "publishTime": datetime.now(UTC).isoformat()}
    return json.dumps({"message": message, "subscription": "projects/estateos-dev/subscriptions/gmail-push"}).encode()
