"""Response schemas for the dashboard API."""

from typing import Any
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict

from app.contracts import Channel, Direction
from app.db.enums import DeliveryStatus, FeedKind, PipelineStatus


class FeedItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    kind: FeedKind
    ref_id: UUID | None
    payload: dict[str, Any]
    created_at: AwareDatetime
    seen_at: AwareDatetime | None
    resolved_at: AwareDatetime | None


class InboxItem(BaseModel):
    thread_key: str
    cursor: str
    channel: Channel
    last_at: AwareDatetime
    last_text: str
    sender: str
    person_name: str | None
    case_id: UUID | None
    unread_pipeline: PipelineStatus
    message_count: int


class AttachmentOut(BaseModel):
    id: UUID
    filename: str | None
    mime_type: str
    size_bytes: int
    url: str


class ThreadMessage(BaseModel):
    id: UUID
    direction: Direction
    sent_at: AwareDatetime
    sender: str
    text: str
    delivery_status: DeliveryStatus | None
    pipeline_status: PipelineStatus
    suspicious: bool
    suspicious_reason: str | None
    attachments: list[AttachmentOut]
