"""Google Chat inbound event parsing and Message conversion."""

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from app.contracts import Channel, Direction, Message
from app.core.errors import EstateOSError


class ChatParseError(EstateOSError):
    """Malformed Google Chat webhook payload."""


@dataclass(frozen=True)
class GoogleChatEvent:
    event_type: str  # "MESSAGE" or "CARD_CLICKED"
    event_time: datetime
    space_name: str  # e.g. "spaces/AAAA..."
    user_name: str  # e.g. "users/1234567890"
    user_display_name: str | None
    message_name: str  # e.g. "spaces/AAAA.../messages/msg123"
    text: str = ""
    button_id: str | None = None  # from CARD_CLICKED action parameter "button_id"


def parse_chat_event(payload: dict[str, Any]) -> GoogleChatEvent:
    """Parses Google Chat webhook event JSON into a GoogleChatEvent."""
    event_type = str(payload.get("type") or "MESSAGE")
    space_name = str(payload.get("space", {}).get("name") or "")
    if not space_name:
        raise ChatParseError("missing space name in chat event")

    user = payload.get("user") or payload.get("message", {}).get("sender") or {}
    user_name = str(user.get("name") or "")
    if not user_name:
        raise ChatParseError("missing user name in chat event")
    user_display_name = user.get("displayName")

    message = payload.get("message", {})
    fallback_name = payload.get("action", {}).get("actionMethodName") or f"{space_name}/events/1"
    message_name = str(message.get("name") or fallback_name)

    # Time parsing
    raw_time = payload.get("eventTime") or message.get("createTime")
    if raw_time:
        try:
            event_time = datetime.fromisoformat(str(raw_time).replace("Z", "+00:00"))
        except ValueError:
            event_time = datetime.now(UTC)
    else:
        event_time = datetime.now(UTC)

    button_id: str | None = None
    text: str = ""

    if event_type == "CARD_CLICKED":
        action = payload.get("action", {})
        params = action.get("parameters", [])
        for p in params:
            if p.get("key") == "button_id":
                button_id = str(p.get("value") or "")
        text = button_id or action.get("actionMethodName") or "clicked"
    else:
        text = str(message.get("text") or "")

    return GoogleChatEvent(
        event_type=event_type,
        event_time=event_time,
        space_name=space_name,
        user_name=user_name,
        user_display_name=user_display_name,
        message_name=message_name,
        text=text,
        button_id=button_id,
    )


def to_message(event: GoogleChatEvent, *, company_id: UUID, raw_event_id: UUID) -> tuple[Message, dict[str, Any]]:
    """Converts a parsed GoogleChatEvent to a standard Message contract and row metadata."""
    meta: dict[str, Any] = {
        "event_type": event.event_type,
        "space": event.space_name,
        "user_name": event.user_name,
        "display_name": event.user_display_name,
    }
    if event.button_id:
        meta["interactive_id"] = event.button_id

    msg = Message(
        channel=Channel.google_chat,
        provider_msg_id=event.message_name,
        thread_ref=event.space_name,
        sender_identity=event.user_name,
        direction=Direction.inbound,
        sent_at=event.event_time,
        text=event.button_id or event.text,
        raw_event_id=raw_event_id,
        company_id=company_id,
    )
    return msg, meta
