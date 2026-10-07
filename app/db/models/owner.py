"""Owner approvals and outbound sends (sends are written only by app.sender)."""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import ForeignKey, Index, String, Text, text
from sqlalchemy.orm import Mapped, mapped_column

from app.contracts import ButtonChoice, Channel
from app.db.base import Base, CompanyScoped, str_enum
from app.db.enums import ApprovalStatus, OutboxStatus, SendStatus


class Approval(Base, CompanyScoped):
    """One request to the owner for one draft version. The sender acts only on an approved, version-matching row."""

    __tablename__ = "approvals"
    __table_args__ = (
        # At most one live approval per draft version: a retried "ask owner" step cannot double-prompt Harjot.
        # Expired/rejected/edited rows may repeat so the owner can be re-asked.
        Index(
            "uq_approvals_live",
            "action_id",
            "draft_version",
            unique=True,
            postgresql_where=text("status IN ('pending', 'approved')"),
        ),
    )

    action_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("actions.id"), index=True)
    draft_version: Mapped[int]
    status: Mapped[ApprovalStatus] = mapped_column(
        str_enum(ApprovalStatus),
        default=ApprovalStatus.pending,
        server_default=ApprovalStatus.pending.value,
        index=True,
    )
    owner_wa_message_id: Mapped[str | None] = mapped_column(String(255))
    choice: Mapped[ButtonChoice | None] = mapped_column(str_enum(ButtonChoice))
    decided_at: Mapped[datetime | None]


class Send(Base, CompanyScoped):
    """Every outbound effect. `idempotency_key` unique makes retries no-ops."""

    __tablename__ = "sends"

    action_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("actions.id"), index=True)
    idempotency_key: Mapped[str] = mapped_column(String(255), unique=True)
    channel: Mapped[Channel] = mapped_column(str_enum(Channel))
    target: Mapped[str] = mapped_column(String(320))
    provider_ref: Mapped[str | None] = mapped_column(String(255))
    status: Mapped[SendStatus] = mapped_column(
        str_enum(SendStatus), default=SendStatus.pending, server_default=SendStatus.pending.value
    )
    error: Mapped[str | None] = mapped_column(Text)
    attempted_at: Mapped[datetime | None]


class OwnerOutbox(Base, CompanyScoped):
    """Owner messages held while the WhatsApp 24-hour window is closed; flushed in order on Harjot's next message.

    `payload` is the built WhatsApp message (recipient included: the owner number from the DB, never model output).
    """

    __tablename__ = "owner_outbox"
    __company_id_leading_index__ = True
    __table_args__ = (Index(None, "company_id", "status", "created_at"),)

    idempotency_key: Mapped[str] = mapped_column(String(255), unique=True)
    payload: Mapped[dict[str, Any]]
    status: Mapped[OutboxStatus] = mapped_column(
        str_enum(OutboxStatus), default=OutboxStatus.queued, server_default=OutboxStatus.queued.value
    )
