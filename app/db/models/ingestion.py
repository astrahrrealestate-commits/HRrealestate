"""Raw provider events and the normalised messages/attachments derived from them."""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import BigInteger, ForeignKey, Index, String, Text, UniqueConstraint, func
from sqlalchemy import text as sql_text  # MessageRow has a column named `text`
from sqlalchemy.orm import Mapped, mapped_column

from app.contracts import Channel, Direction
from app.db.base import Base, CompanyScoped, str_enum
from app.db.enums import DeliveryStatus, ExtractionStatus, PipelineStatus, RawEventStatus

THREAD_KEY_SQL = "coalesce(thread_ref, provider_msg_id)"  # a message's thread key (what thread pages filter on)


class RawEvent(Base, CompanyScoped):
    """Exactly what the provider sent, stored before any processing (Postgres first)."""

    __tablename__ = "raw_events"
    __company_id_leading_index__ = True
    # Per company: provider ids (e.g. Gmail message ids) are only unique within one account/mailbox.
    __table_args__ = (UniqueConstraint("company_id", "provider", "provider_msg_id"),)

    provider: Mapped[Channel] = mapped_column(str_enum(Channel))
    provider_msg_id: Mapped[str] = mapped_column(String(255))
    payload: Mapped[dict[str, Any]]
    status: Mapped[RawEventStatus] = mapped_column(
        str_enum(RawEventStatus),
        default=RawEventStatus.pending,
        server_default=RawEventStatus.pending.value,
        index=True,
    )
    attempts: Mapped[int] = mapped_column(default=0, server_default="0")
    last_error: Mapped[str | None] = mapped_column(Text)
    received_at: Mapped[datetime] = mapped_column(server_default=func.now())


class MessageRow(Base, CompanyScoped):
    __tablename__ = "messages"
    __company_id_leading_index__ = True
    __table_args__ = (
        UniqueConstraint("company_id", "channel", "provider_msg_id"),
        Index(None, "company_id", "thread_ref"),
        Index(None, "pipeline_status", "pipeline_attempts"),  # hourly pipeline requeue sweep
        # Thread page scan (page_memory/page_facts: channel + thread key); expression index, migration 0012
        Index("ix_messages_company_channel_thread", "company_id", "channel", sql_text(THREAD_KEY_SQL)),
        Index(None, "company_id", "created_at"),  # newest message per company: page pre-warm freshness (0016)
    )

    raw_event_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("raw_events.id"), index=True)
    channel: Mapped[Channel] = mapped_column(str_enum(Channel))
    provider_msg_id: Mapped[str] = mapped_column(String(255))
    thread_ref: Mapped[str | None] = mapped_column(String(255))
    sender_identity: Mapped[str] = mapped_column(String(320), index=True)
    direction: Mapped[Direction] = mapped_column(str_enum(Direction))
    sent_at: Mapped[datetime]
    text: Mapped[str] = mapped_column(Text)
    person_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("people.id"), index=True)
    delivery_status: Mapped[DeliveryStatus | None] = mapped_column(str_enum(DeliveryStatus))
    # Channel extras: interactive reply ids, Gmail headers/labels. Column is `meta`: `metadata` is reserved by
    # SQLAlchemy's declarative base.
    meta: Mapped[dict[str, Any]] = mapped_column(default=dict, server_default=sql_text("'{}'::jsonb"))
    # Agent pipeline progress (inbound messages routed to the pipeline); failed runs are requeued up to 3 times.
    pipeline_status: Mapped[PipelineStatus] = mapped_column(
        str_enum(PipelineStatus), default=PipelineStatus.pending, server_default=PipelineStatus.pending.value
    )
    pipeline_error: Mapped[str | None] = mapped_column(Text)
    pipeline_attempts: Mapped[int] = mapped_column(default=0, server_default="0")


class AttachmentRow(Base, CompanyScoped):
    __tablename__ = "attachments"

    message_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("messages.id"), index=True)
    s3_key: Mapped[str] = mapped_column(String(1024))
    mime_type: Mapped[str] = mapped_column(String(255))
    filename: Mapped[str | None] = mapped_column(String(255))
    size_bytes: Mapped[int] = mapped_column(BigInteger)
    sha256: Mapped[str] = mapped_column(String(64))
    extracted_text: Mapped[str | None] = mapped_column(Text)
    extraction_status: Mapped[ExtractionStatus | None] = mapped_column(str_enum(ExtractionStatus))
    page_count: Mapped[int | None]
    extractor: Mapped[str | None] = mapped_column(String(32))  # which reader produced extracted_text
