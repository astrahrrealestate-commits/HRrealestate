"""Companies, their channel endpoints and owner accounts."""

import uuid
from datetime import datetime, time
from typing import Any

from sqlalchemy import ForeignKey, String, UniqueConstraint, false, text
from sqlalchemy.orm import Mapped, mapped_column

from app.contracts import Channel, InteractiveChannel
from app.db.base import Base, CompanyScoped, CreatedAtMixin, IdMixin, str_enum


class Company(Base, IdMixin, CreatedAtMixin):
    __tablename__ = "companies"

    name: Mapped[str] = mapped_column(String(200))
    timezone: Mapped[str] = mapped_column(String(64), default="Europe/Amsterdam", server_default="Europe/Amsterdam")
    paused: Mapped[bool] = mapped_column(default=False, server_default=false())
    # Agent settings (spec phase-1 agents). Phase 1 sets these by seed/SQL; there is no admin UI.
    chase_after_days: Mapped[int] = mapped_column(default=3, server_default="3")  # business days
    escalate_after_chases: Mapped[int] = mapped_column(default=2, server_default="2")
    briefing_time: Mapped[time] = mapped_column(default=time(7, 30), server_default="07:30")
    weekly_weekday: Mapped[int] = mapped_column(default=4, server_default="4")  # Monday = 0
    weekly_time: Mapped[time] = mapped_column(default=time(16, 0), server_default="16:00")
    drift_thresholds: Mapped[dict[str, Any]] = mapped_column(default=dict, server_default=text("'{}'::jsonb"))


class ChannelAccount(Base, CompanyScoped):
    """A provider endpoint we receive on: a WhatsApp phone_number_id or a Gmail mailbox."""

    __tablename__ = "channel_accounts"
    __table_args__ = (UniqueConstraint("channel", "address"),)

    channel: Mapped[Channel] = mapped_column(str_enum(Channel))
    address: Mapped[str] = mapped_column(String(320))
    is_owner_channel: Mapped[bool] = mapped_column(default=False, server_default=false())


class OwnerAccount(Base, CompanyScoped):
    __tablename__ = "owner_accounts"
    __company_id_leading_index__ = True
    __table_args__ = (UniqueConstraint("company_id", "whatsapp_e164"),)

    display_name: Mapped[str] = mapped_column(String(200))
    whatsapp_e164: Mapped[str] = mapped_column(String(20))
    email: Mapped[str | None] = mapped_column(String(320))
    chat_user: Mapped[str | None] = mapped_column(String(200))
    interactive_channel: Mapped[InteractiveChannel | None] = mapped_column(
        str_enum(InteractiveChannel), default=InteractiveChannel.whatsapp, server_default="whatsapp"
    )


class GmailSyncState(Base, CompanyScoped):
    __tablename__ = "gmail_sync_state"

    channel_account_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("channel_accounts.id"), unique=True)
    history_id: Mapped[str | None] = mapped_column(String(32))  # Gmail historyId is an unsigned 64-bit string
    watch_expires_at: Mapped[datetime | None]
