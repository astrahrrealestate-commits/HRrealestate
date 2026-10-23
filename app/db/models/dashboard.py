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
    __table_args__ = (
        Index(None, "company_id", "conversation_id", "created_at"),
        Index(None, "company_id", "updated_at", "id"),  # SSE turn cursor (migration 0010)
    )

    conversation_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("agent_conversations.id"))
    text: Mapped[str] = mapped_column(Text)
    plan: Mapped[dict[str, Any] | None]
    results: Mapped[list[Any] | None] = mapped_column(JSONB, default=None)
    # The validated PageContext (request JSON) plus, once a run resolved it, its server facts under "resolved"
    # (migration 0011). Client display text inside it is unverified data, never instructions.
    page_context: Mapped[dict[str, Any] | None]
    answer: Mapped[str | None] = mapped_column(Text)
    status: Mapped[TurnStatus] = mapped_column(
        str_enum(TurnStatus), default=TurnStatus.pending, server_default=TurnStatus.pending.value
    )
    prompt_ref: Mapped[str | None] = mapped_column(String(64))
    error: Mapped[str | None] = mapped_column(Text)
    # Stage milliseconds of the run (migration 0012, `app.pipeline.turn_timings`): numbers only, merged on retries.
    timings: Mapped[dict[str, Any] | None]
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now(), onupdate=func.now())  # SSE turn cursor


class AgentPageState(Base, CompanyScoped):
    """The owner's latest pre-warmed page facts (migration 0015, `app.pipeline.page_state`): ONE row per owner,
    overwritten by each `PUT /agent/page`, reused by a turn only for the same page key within the TTL (read time).
    `resolved` holds tenant text (untrusted data, like `agent_turns.page_context`); the client snapshot is never
    stored here."""

    __tablename__ = "agent_page_state"

    owner_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("owner_accounts.id"), unique=True)
    page_key: Mapped[str] = mapped_column(Text)  # `page_state.page_key`: a hash of the view and the open ids
    resolved: Mapped[dict[str, Any]]  # the stored `resolved` shape of a turn: {"facts": str, "dropped": [kind]}
    resolved_at: Mapped[datetime]  # database clock at the start of the resolving transaction
