"""Agent work items: owner tasks (#6), waiting-for items (#5) and filed documents (#9)."""

import uuid
from datetime import date, datetime
from typing import Any

from pgvector.sqlalchemy import Vector
from sqlalchemy import ForeignKey, Index, String, Text, false, text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.settings import EMBEDDING_DIMENSIONS
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
        Index(None, "source_action_id"),
        Index(
            "uq_waits_open",
            "case_id",
            "party_person_id",
            unique=True,
            postgresql_where=text("status = 'waiting'"),
            postgresql_nulls_not_distinct=True,  # a wait on "whoever answers" (no party) is one per case too
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
    """One filing decision per attachment. `summary`/`facts` come from reading the extracted text (M10), else null."""

    __tablename__ = "documents"
    __table_args__ = (
        Index(None, "model_call_id"),
        Index("ix_documents_doc_embedding", "doc_embedding", postgresql_using="hnsw",
              postgresql_ops={"doc_embedding": "vector_cosine_ops"}),
    )  # fmt: skip

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
    summary: Mapped[str | None] = mapped_column(Text)
    facts: Mapped[dict[str, Any] | None]  # DocumentFacts.key_facts, typed per doc_type
    document_date: Mapped[date | None]
    reader_version: Mapped[str | None] = mapped_column(String(16))
    suspicious: Mapped[bool] = mapped_column(
        default=False, server_default=false()
    )  # injection scan hit: not draft context
    # Company reference library (M13): general terms readable by every dossier. Set by the owner, never by the pipeline.
    is_reference: Mapped[bool] = mapped_column(default=False, server_default=false())
    index_version: Mapped[str | None] = mapped_column(String(8))  # chunking/embedding recipe of this document's chunks
    doc_embedding: Mapped[Any | None] = mapped_column(
        Vector(EMBEDDING_DIMENSIONS)
    )  # title + summary + parties + unit (ADR 0008)
