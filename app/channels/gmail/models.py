"""Gmail API v1 message (`users.messages.get`, `format=raw`): metadata from the API, content as raw RFC 822 bytes."""

import base64
import binascii
from datetime import UTC, datetime
from typing import Annotated, Any

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field, field_serializer


def _b64url(value: Any) -> bytes:
    if not isinstance(value, str) or not value:
        raise ValueError("raw must be a non-empty base64url string")
    try:
        data = base64.b64decode(value.translate(str.maketrans("-_", "+/")) + "=" * (-len(value) % 4), validate=True)
    except (binascii.Error, ValueError) as exc:
        raise ValueError("raw is not valid base64url") from exc
    if not data:
        raise ValueError("raw decodes to nothing")
    return data


_MIN_MS = int(datetime(2000, 1, 1, tzinfo=UTC).timestamp() * 1000)
_MAX_MS = int(datetime(2100, 1, 1, tzinfo=UTC).timestamp() * 1000)


def _epoch_ms(value: Any) -> datetime:
    text = str(value)
    if not text.isascii() or not text.isdigit() or not _MIN_MS <= int(text) < _MAX_MS:
        raise ValueError("internalDate must be epoch milliseconds within 2000..2100")
    return datetime.fromtimestamp(int(text) / 1000, UTC)


class GmailMessage(BaseModel):
    model_config = ConfigDict(frozen=True, extra="ignore", populate_by_name=True)

    id: str = Field(min_length=1)
    thread_id: str = Field(alias="threadId", min_length=1)
    label_ids: list[str] = Field(alias="labelIds", default_factory=list)
    history_id: int = Field(alias="historyId", default=0)
    internal_date: Annotated[datetime, BeforeValidator(_epoch_ms)] = Field(alias="internalDate")
    raw: Annotated[bytes, BeforeValidator(_b64url)]

    @field_serializer("internal_date")
    def _epoch_ms_out(self, value: datetime) -> str:
        return str(int(value.timestamp() * 1000))

    @field_serializer("raw")
    def _raw_b64url(self, raw: bytes) -> str:
        """Round-trips through JSON (raw mail is rarely valid UTF-8)."""
        return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def parse_api_message(data: dict[str, Any]) -> GmailMessage:
    """Validate a raw-format API message. Raises ValueError (pydantic ValidationError) on malformed input."""
    return GmailMessage.model_validate(data)
