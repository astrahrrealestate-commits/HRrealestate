"""Response models of the Chats API. Message text is returned as data and never logged."""

from uuid import UUID

from pydantic import AwareDatetime, BaseModel

from app.api.v1.schemas import AttachmentOut
from app.contracts import Direction
from app.db.enums import DeliveryStatus, PersonKind


class ChatItem(BaseModel):
    """One row of the chat list: the contact, the latest message and the unread badge. `cursor` pages the list."""

    chat_key: str
    name: str | None
    person_kind: PersonKind | None
    last_message_id: UUID
    last_at: AwareDatetime
    last_text: str
    last_kind: str | None
    last_direction: Direction
    last_delivery: DeliveryStatus | None
    last_pending: bool
    unread: int
    cursor: str


class ChatQuote(BaseModel):
    id: UUID
    text: str


class ChatMessage(BaseModel):
    id: UUID
    direction: Direction
    sent_at: AwareDatetime
    text: str
    kind: str | None
    delivery_status: DeliveryStatus | None
    error: str | None
    suspicious: bool
    suspicious_reason: str | None
    reply_to: ChatQuote | None
    attachments: list[AttachmentOut]
    pending: bool


class ChatThread(BaseModel):
    chat_key: str
    name: str | None
    person_kind: PersonKind | None
    case_id: UUID | None
    messages: list[ChatMessage]
