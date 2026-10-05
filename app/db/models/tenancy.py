"""Companies, their channel endpoints and owner accounts."""

import uuid
from datetime import datetime

from sqlalchemy import ForeignKey, String, UniqueConstraint, false
from sqlalchemy.orm import Mapped, mapped_column

from app.contracts import Channel
from app.db.base import Base, CompanyScoped, CreatedAtMixin, IdMixin, str_enum


class Company(Base, IdMixin, CreatedAtMixin):
    __tablename__ = "companies"

    name: Mapped[str] = mapped_column(String(200))
    timezone: Mapped[str] = mapped_column(String(64), default="Europe/Berlin", server_default="Europe/Berlin")
    paused: Mapped[bool] = mapped_column(default=False, server_default=false())


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


class GmailSyncState(Base, CompanyScoped):
    __tablename__ = "gmail_sync_state"

    channel_account_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("channel_accounts.id"), unique=True)
    history_id: Mapped[str | None] = mapped_column(String(32))  # Gmail historyId is an unsigned 64-bit string
    watch_expires_at: Mapped[datetime | None]
