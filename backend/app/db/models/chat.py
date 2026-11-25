"""WhatsApp-style Chats read state: when Harjot last opened each conversation (drives the unread badge)."""

from datetime import datetime

from sqlalchemy import String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, CompanyScoped


class ChatRead(Base, CompanyScoped):
    """One read marker per chat. `chat_key` names the conversation (a person, or an unlinked sender identity)."""

    __tablename__ = "chat_reads"
    __company_id_leading_index__ = True
    __table_args__ = (UniqueConstraint("company_id", "chat_key"),)

    chat_key: Mapped[str] = mapped_column(String(32))
    last_read_at: Mapped[datetime] = mapped_column()
