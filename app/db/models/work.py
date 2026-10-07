"""Agent work items: owner tasks (#6), waiting-for items (#5) and filed documents (#9)."""

import uuid
from datetime import datetime

from sqlalchemy import ForeignKey, Index, String, Text, text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, CompanyScoped, str_enum
from app.db.enums import DocumentStatus, TaskPriority, TaskStatus, WaitStatus


class TaskRow(Base, CompanyScoped):
    """Created by code only (never by the model). `assignee`: "owner", "system" or "person:<uuid>"."""

    __tablename__ = "tasks"
    __company_id_leading_index__ = True
    __table_args__ = (
        Index(None, "company_id", "status", "due_at"),
        Index(
            "uq_tasks_action_source",
            "action_id",
            "source",
            unique=True,
            postgresql_where=text("action_id IS NOT NULL"),
        ),
    )

    case_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("cases.id"), index=True)
    action_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("actions.id"))
    title: Mapped[str] = mapped_column(String(200))
    assignee: Mapped[str] = mapped_column(String(64))
    due_at: Mapped[datetime | None]
    priority: Mapped[TaskPriority] = mapped_column(
        str_enum(TaskPriority), default=TaskPriority.p2, server_default=TaskPriority.p2.value
    )
    status: Mapped[TaskStatus] = mapped_column(
        str_enum(TaskStatus), default=TaskStatus.open, server_default=TaskStatus.open.value
    )
    snoozed_until: Mapped[datetime | None]
    done_at: Mapped[datetime | None]
    source: Mapped[str] = mapped_column(String(32))  # approval | reminder | escalation | owner


class WaitRow(Base, CompanyScoped):
    """Someone owes an answer on a case by `expected_by`. At most one open wait per (case, party)."""

    __tablename__ = "waits"
    __table_args__ = (
        Index(None, "status", "expected_by"),
        Index(
            "uq_waits_open",
            "case_id",
            "party_person_id",
            unique=True,
            postgresql_where=text("status = 'waiting'"),
        ),
    )

    case_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("cases.id"), index=True)
    party_person_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("people.id"), index=True)
    about: Mapped[str] = mapped_column(String(300))
    expected_by: Mapped[datetime]
    status: Mapped[WaitStatus] = mapped_column(
        str_enum(WaitStatus), default=WaitStatus.waiting, server_default=WaitStatus.waiting.value
    )
    chase_count: Mapped[int] = mapped_column(default=0, server_default="0")
    last_chased_at: Mapped[datetime | None]
    source_action_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("actions.id"))


class DocumentRow(Base, CompanyScoped):
    """One filing decision per attachment. Phase 1 classifies from metadata only (contents are never read)."""

    __tablename__ = "documents"

    attachment_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("attachments.id"), unique=True)
    doc_type: Mapped[str] = mapped_column(String(32))  # app.contracts DocType value
    title: Mapped[str] = mapped_column(String(200))
    file_name: Mapped[str] = mapped_column(String(255))
    confidence: Mapped[float]
    status: Mapped[DocumentStatus] = mapped_column(
        str_enum(DocumentStatus), default=DocumentStatus.pending, server_default=DocumentStatus.pending.value
    )
    drive_file_id: Mapped[str | None] = mapped_column(String(128))
    drive_folder: Mapped[str | None] = mapped_column(String(255))
    model_call_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("model_calls.id"))
    error: Mapped[str | None] = mapped_column(Text)
