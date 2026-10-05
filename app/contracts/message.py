"""`Message`: the one normalised format for inbound/outbound traffic on every channel."""

from typing import Annotated
from uuid import UUID

import phonenumbers
from email_validator import EmailNotValidError, validate_email
from pydantic import AfterValidator, AwareDatetime, Field, StringConstraints

from app.contracts.common import Channel, Contract, Direction, NonBlankStr


def normalise_identity(value: str, default_region: str = "DE") -> str:
    """E.164 for phone numbers, lowercase for emails. Raises ValueError for anything else."""
    raw = value.strip()
    if not raw:
        raise ValueError("empty sender identity")
    if raw.isascii() and raw.isdigit() and not raw.startswith("0"):
        # WhatsApp Cloud API sends international numbers as bare ASCII digits ("4915123456789"). Assumption: only
        # WhatsApp produces bare digits; a German number typed without its trunk "0" would be misread as international.
        raw = f"+{raw}"
    if "@" in raw:
        try:
            return validate_email(raw, check_deliverability=False).normalized.lower()
        except EmailNotValidError as exc:
            raise ValueError(f"invalid email identity: {exc}") from exc
    try:
        number = phonenumbers.parse(raw, default_region)
    except phonenumbers.NumberParseException as exc:
        raise ValueError(f"invalid phone identity: {exc}") from exc
    if not phonenumbers.is_valid_number(number):
        raise ValueError("invalid phone identity: not a valid number")
    return phonenumbers.format_number(number, phonenumbers.PhoneNumberFormat.E164)


Identity = Annotated[str, AfterValidator(normalise_identity)]


class Attachment(Contract):
    s3_key: NonBlankStr
    mime_type: NonBlankStr
    filename: str | None
    size_bytes: Annotated[int, Field(ge=0)]
    sha256: Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]


class Message(Contract):
    channel: Channel
    provider_msg_id: NonBlankStr
    thread_ref: str | None  # opaque provider thread key (WA: counterpart, normalised by the adapter; Gmail: threadId)
    sender_identity: Identity
    direction: Direction
    sent_at: AwareDatetime
    text: str
    attachments: list[Attachment] = Field(default_factory=list)
    raw_event_id: UUID
    company_id: UUID
