"""Pydantic models of the WhatsApp Cloud API webhook (documented shape; also what 360dialog forwards).

Robustness contract (tested): every list at every level is `list[Any]` and validated item by item, so one malformed
entry/change/contact/message/status never drops its siblings. Edge models ignore unknown fields (Meta adds fields
without notice). Timestamps are parsed and bounds-checked here, so a bad one fails only its own item.
"""

from datetime import UTC, datetime
from enum import StrEnum
from typing import Annotated, Any

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field

_MIN_TS = int(datetime(2000, 1, 1, tzinfo=UTC).timestamp())
_MAX_TS = int(datetime(2100, 1, 1, tzinfo=UTC).timestamp())


def _parse_timestamp(value: Any) -> datetime:
    text = str(value)
    if not text.isascii() or not text.isdigit():
        raise ValueError("timestamp must be unix seconds (digits only)")
    seconds = int(text)
    if not _MIN_TS <= seconds < _MAX_TS:
        raise ValueError("timestamp out of range")
    return datetime.fromtimestamp(seconds, UTC)


Timestamp = Annotated[datetime, BeforeValidator(_parse_timestamp)]


class _Edge(BaseModel):
    model_config = ConfigDict(extra="ignore", populate_by_name=True)


class Metadata(_Edge):
    display_phone_number: str
    phone_number_id: str


class Profile(_Edge):
    name: str | None = None


class Contact(_Edge):
    wa_id: str | None = None
    profile: Profile | None = None


class Media(_Edge):
    id: str | None = None
    mime_type: str | None = None
    sha256: str | None = None
    caption: str | None = None
    filename: str | None = None


class Text(_Edge):
    body: str | None = None


class Reply(_Edge):
    id: str | None = None
    title: str = ""
    description: str | None = None


class Interactive(_Edge):
    type: str | None = None
    button_reply: Reply | None = None
    list_reply: Reply | None = None


class LegacyButton(_Edge):
    """Template quick-reply button (the only reply path outside the 24h customer-service window)."""

    payload: str | None = None
    text: str | None = None


class Reaction(_Edge):
    message_id: str | None = None
    emoji: str | None = None


class Location(_Edge):
    latitude: float | None = None
    longitude: float | None = None
    name: str | None = None
    address: str | None = None


class System(_Edge):
    body: str | None = None
    type: str | None = None
    new_wa_id: str | None = None


class SharedContactName(_Edge):
    formatted_name: str | None = None


class SharedContact(_Edge):
    name: SharedContactName | None = None


class Context(_Edge):
    id: str | None = None


class RawMessage(_Edge):
    sender: str | None = Field(default=None, alias="from")  # absent for senders without a phone id
    id: str
    timestamp: Timestamp
    type: str
    text: Text | None = None
    image: Media | None = None
    document: Media | None = None
    audio: Media | None = None
    video: Media | None = None
    sticker: Media | None = None
    interactive: Interactive | None = None
    button: LegacyButton | None = None
    reaction: Reaction | None = None
    location: Location | None = None
    system: System | None = None
    contacts: list[SharedContact] | None = None
    context: Context | None = None


class RawEcho(RawMessage):
    to: str


class StatusKind(StrEnum):
    sent = "sent"
    delivered = "delivered"
    read = "read"
    failed = "failed"


class StatusError(_Edge):
    code: int | None = None
    title: str | None = None


class RawStatus(_Edge):
    id: str
    status: StatusKind  # other values (e.g. "deleted", "warning") fail validation and are skipped with a log line
    timestamp: Timestamp
    recipient_id: str | None = None
    errors: list[Any] = Field(default_factory=list)  # validated per item in the parser


class Value(_Edge):
    metadata: Metadata
    contacts: list[Any] = Field(default_factory=list)
    messages: list[Any] = Field(default_factory=list)
    statuses: list[Any] = Field(default_factory=list)
    message_echoes: list[Any] = Field(default_factory=list)


class Change(_Edge):
    field: str
    value: dict[str, Any]


class Entry(_Edge):
    changes: list[Any] = Field(default_factory=list)


class Webhook(_Edge):
    object: str
    entry: list[Any] = Field(default_factory=list)
