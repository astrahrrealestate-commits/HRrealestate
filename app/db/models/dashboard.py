"""Dashboard owner feed and Super Agent conversations."""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import ForeignKey, Index, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, CompanyScoped, str_enum
from app.db.enums import FeedKind, TurnStatus


class OwnerFeed(Base, CompanyScoped):
    """What the owner sees in the dashboard. Postgres is the source of truth; SSE only nudges the client."""

    __tablename__ = "owner_feed"
    __company_id_leading_index__ = True
    __table_args__ = (Index(None, "company_id", "created_at", "id"),)

    idempotency_key: Mapped[str] = mapped_column(String(255), unique=True)
    kind: Mapped[FeedKind] = mapped_column(str_enum(FeedKind))
    ref_id: Mapped[uuid.UUID | None]
    payload: Mapped[dict[str, Any]]
    seen_at: Mapped[datetime | None]
    resolved_at: Mapped[datetime | None]


class AgentConversation(Base, CompanyScoped):
    __tablename__ = "agent_conversations"

    owner_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("owner_accounts.id"))


class AgentTurn(Base, CompanyScoped):
    __tablename__ = "agent_turns"
    __company_id_leading_index__ = True
    __table_args__ = (Index(None, "company_id", "conversation_id", "created_at"),)

    conversation_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("agent_conversations.id"))
    text: Mapped[str] = mapped_column(Text)
    plan: Mapped[dict[str, Any] | None]
    results: Mapped[list[Any] | None] = mapped_column(JSONB, default=None)
    answer: Mapped[str | None] = mapped_column(Text)
    status: Mapped[TurnStatus] = mapped_column(
        str_enum(TurnStatus), default=TurnStatus.pending, server_default=TurnStatus.pending.value
    )
    prompt_ref: Mapped[str | None] = mapped_column(String(64))
    error: Mapped[str | None] = mapped_column(Text)
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now(), onupdate=func.now())  # SSE turn cursor
