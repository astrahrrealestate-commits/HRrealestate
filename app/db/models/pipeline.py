"""Understanding, cases and proposed actions."""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import ForeignKey, Index, String, Text, UniqueConstraint, Uuid, func
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import Mapped, mapped_column

from app.contracts import ActionType, CaseState, Category, Urgency
from app.db.base import Base, CompanyScoped, str_enum
from app.db.enums import ActionStatus, CaseEventKind, LinkMethod


class UnderstandingRow(Base, CompanyScoped):
    __tablename__ = "understandings"

    message_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("messages.id"), unique=True)
    model_call_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("model_calls.id"), index=True)
    category: Mapped[Category] = mapped_column(str_enum(Category), index=True)
    urgency: Mapped[Urgency] = mapped_column(str_enum(Urgency), index=True)
    body: Mapped[dict[str, Any]]  # full Understanding contract JSON
    prompt_version: Mapped[str] = mapped_column(String(64))


class Case(Base, CompanyScoped):
    __tablename__ = "cases"
    __company_id_leading_index__ = True
    __table_args__ = (Index(None, "company_id", "state"),)

    unit_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("units.id"), index=True)
    lease_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("leases.id"), index=True)
    primary_person_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("people.id"), index=True)
    state: Mapped[CaseState] = mapped_column(
        str_enum(CaseState), default=CaseState.open, server_default=CaseState.open.value
    )
    category: Mapped[Category] = mapped_column(str_enum(Category))
    urgency: Mapped[Urgency] = mapped_column(str_enum(Urgency))
    summary: Mapped[str] = mapped_column(Text, default="", server_default="")
    summary_version: Mapped[int] = mapped_column(default=0, server_default="0")
    opened_at: Mapped[datetime] = mapped_column(server_default=func.now())
    resolved_at: Mapped[datetime | None]


class CaseLink(Base, CompanyScoped):
    __tablename__ = "case_links"

    case_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("cases.id"), index=True)
    message_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("messages.id"), unique=True)
    method: Mapped[LinkMethod] = mapped_column(str_enum(LinkMethod))
    confidence: Mapped[float | None]


class CaseEvent(Base, CompanyScoped):
    """Append-only audit trail of a case."""

    __tablename__ = "case_events"
    __company_id_leading_index__ = True
    __table_args__ = (Index(None, "company_id", "created_at"),)  # newest event per company: pre-warm freshness (0016)

    case_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("cases.id"), index=True)
    kind: Mapped[CaseEventKind] = mapped_column(str_enum(CaseEventKind))
    from_state: Mapped[CaseState | None] = mapped_column(str_enum(CaseState))
    to_state: Mapped[CaseState | None] = mapped_column(str_enum(CaseState))
    note: Mapped[str | None] = mapped_column(Text)
    actor: Mapped[str] = mapped_column(String(64))  # "system", "owner", "agent:<name>"


class ActionRow(Base, CompanyScoped):
    __tablename__ = "actions"

    case_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("cases.id"), index=True)
    type: Mapped[ActionType] = mapped_column(str_enum(ActionType))
    payload: Mapped[dict[str, Any]]
    rationale: Mapped[str] = mapped_column(Text)
    context_ref: Mapped[list[uuid.UUID]] = mapped_column(ARRAY(Uuid))
    draft_version: Mapped[int] = mapped_column(default=1, server_default="1")
    status: Mapped[ActionStatus] = mapped_column(
        str_enum(ActionStatus), default=ActionStatus.proposed, server_default=ActionStatus.proposed.value, index=True
    )


class ActionRevision(Base, CompanyScoped):
    __tablename__ = "action_revisions"
    __table_args__ = (UniqueConstraint("action_id", "draft_version"),)

    action_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("actions.id"), index=True)
    draft_version: Mapped[int]
    payload: Mapped[dict[str, Any]]
    edited_by: Mapped[str] = mapped_column(String(64))
