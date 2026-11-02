"""Message RAG (WhatsApp & Gmail): searchable message chunks and per-message indexing state."""

import uuid
from datetime import datetime
from typing import Any

from pgvector.sqlalchemy import Vector
from sqlalchemy import Boolean, Computed, ForeignKey, Index, Integer, String, Text, UniqueConstraint, Uuid, func
from sqlalchemy.dialects.postgresql import ARRAY, TSVECTOR
from sqlalchemy.orm import Mapped, mapped_column

from app.core.settings import EMBEDDING_DIMENSIONS
from app.db.base import Base, CompanyScoped, str_enum
from app.db.enums import MessageIndexStatus

_INDEXED = "coalesce(context, '') || ' ' || text"
_TSV = f"to_tsvector('dutch'::regconfig, {_INDEXED}) || to_tsvector('simple'::regconfig, {_INDEXED})"


class MessageChunk(Base, CompanyScoped):
    """A continuous conversational window within a thread (target 300-500 tokens).
    Searchable via full-text (tsv in Dutch + Simple) and vector embeddings (pgvector cosine)."""

    __tablename__ = "message_chunks"
    __company_id_leading_index__ = True
    __table_args__ = (
        UniqueConstraint("company_id", "channel", "first_message_id", name="uq_message_chunks_thread_first_msg"),
        Index("ix_message_chunks_tsv", "tsv", postgresql_using="gin"),
        Index(
            "ix_message_chunks_embedding",
            "embedding",
            postgresql_using="hnsw",
            postgresql_ops={"embedding": "vector_cosine_ops"},
        ),
        Index("ix_message_chunks_case_ids", "case_ids", postgresql_using="gin"),
        Index("ix_message_chunks_participant_ids", "participant_ids", postgresql_using="gin"),
        Index("ix_message_chunks_person_timeline", "company_id", "person_id", "last_sent_at"),
        Index("ix_message_chunks_unit_timeline", "company_id", "unit_id", "last_sent_at"),
        Index("ix_message_chunks_company_sent", "company_id", "last_sent_at"),
    )

    channel: Mapped[str] = mapped_column(String(32))
    thread_ref: Mapped[str] = mapped_column(String(255))
    message_ids: Mapped[list[uuid.UUID]] = mapped_column(ARRAY(Uuid))
    first_message_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("messages.id", ondelete="RESTRICT"))
    last_message_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("messages.id", ondelete="RESTRICT"))
    person_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("people.id", ondelete="SET NULL"))
    participant_ids: Mapped[list[uuid.UUID]] = mapped_column(ARRAY(Uuid), default=list)
    unit_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("units.id", ondelete="SET NULL"))
    lease_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("leases.id", ondelete="SET NULL"))
    case_ids: Mapped[list[uuid.UUID]] = mapped_column(ARRAY(Uuid), default=list)
    has_inbound: Mapped[bool] = mapped_column(Boolean, default=False)
    has_outbound: Mapped[bool] = mapped_column(Boolean, default=False)
    first_sent_at: Mapped[datetime]
    last_sent_at: Mapped[datetime]
    subject: Mapped[str | None] = mapped_column(Text)
    categories: Mapped[list[str]] = mapped_column(ARRAY(String(32)), default=list)
    max_urgency: Mapped[str | None] = mapped_column(String(32))
    attachment_ids: Mapped[list[uuid.UUID]] = mapped_column(ARRAY(Uuid), default=list)
    context: Mapped[str | None] = mapped_column(Text)
    text: Mapped[str] = mapped_column(Text)
    tsv: Mapped[Any] = mapped_column(TSVECTOR, Computed(_TSV, persisted=True))
    embedding: Mapped[Any | None] = mapped_column(Vector(EMBEDDING_DIMENSIONS))
    embed_model: Mapped[str | None] = mapped_column(String(64))
    embed_dim: Mapped[int] = mapped_column(Integer, default=1024)
    content_hash: Mapped[str] = mapped_column(String(64))
    is_open: Mapped[bool] = mapped_column(Boolean, default=True)
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now(), onupdate=func.now())


class MessageIndexState(Base):
    """Tracks per-message indexing status for gating, backfills, retries, and auditability."""

    __tablename__ = "message_index_state"
    __table_args__ = (
        Index("ix_message_index_state_status", "status", "updated_at"),
    )

    message_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("messages.id", ondelete="CASCADE"), primary_key=True)
    company_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("companies.id", ondelete="RESTRICT"))
    status: Mapped[MessageIndexStatus] = mapped_column(str_enum(MessageIndexStatus))
    reason: Mapped[str | None] = mapped_column(String(100))
    chunk_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("message_chunks.id", ondelete="SET NULL"))
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    last_error: Mapped[str | None] = mapped_column(Text)
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now(), onupdate=func.now())
