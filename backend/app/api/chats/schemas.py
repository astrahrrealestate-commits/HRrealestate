"""Response models of the Chats API. Message text is returned as data and never logged."""

from typing import Literal
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict, field_validator

from app.api.v1.schemas import AttachmentOut
from app.channels.whatsapp.payloads import TEXT_BODY_MAX
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
    client_msg_id: str | None


ComposerKind = Literal["open", "window_closed", "draft_mode", "paused", "no_recipient"]


class ComposerState(BaseModel):
    """Whether the owner can type a reply now. The sender re-checks every gate; this only explains the disabled box."""

    state: ComposerKind
    window_closes_at: AwareDatetime | None


class ChatThread(BaseModel):
    chat_key: str
    name: str | None
    person_kind: PersonKind | None
    case_id: UUID | None
    messages: list[ChatMessage]
    composer: ComposerState


class SendChatMessageRequest(BaseModel):
    """What the owner typed. The chat is the URL's, the recipient is the stored chat's: nothing else goes in."""

    model_config = ConfigDict(extra="forbid")

    client_msg_id: UUID  # the browser's id of this message: the dedupe key and the send's idempotency key
    text: str  # stored and sent exactly as typed
    suggestion_action_id: UUID | None = None

    @field_validator("text")
    @classmethod
    def _text_fits(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("message is empty")
        if len(value) > TEXT_BODY_MAX or "\x00" in value:  # what is sent is the unstripped text; Postgres refuses NUL
            raise ValueError("message is too long or has a NUL character")
        return value


class SuggestionsOut(BaseModel):
    action_id: UUID | None
    variants: list[str]
