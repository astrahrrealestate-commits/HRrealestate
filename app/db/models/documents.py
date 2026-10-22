"""Document intelligence (M10): searchable chunks, links to the directory, and Drive reorganisation plans."""

import uuid
from datetime import datetime
from typing import Any

from pgvector.sqlalchemy import Vector
from sqlalchemy import Computed, Float, ForeignKey, Index, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import TSVECTOR
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, CompanyScoped, str_enum
from app.db.enums import DocLinkKind, ReorgItemStatus, ReorgPlanStatus

EMBEDDING_DIMENSIONS = 1024  # text-embedding-3-small at 1024 dimensions; one size for every embedder (ADR 0008)
_INDEXED = "coalesce(context, '') || ' ' || text"
_TSV = f"to_tsvector('dutch'::regconfig, {_INDEXED}) || to_tsvector('simple'::regconfig, {_INDEXED})"


class DocumentChunk(Base, CompanyScoped):
    """A slice of a document's text (~400 tokens, page and heading known). `context` is the document header prefixed
    for indexing only (ADR 0008); `tsv` is generated from context + text, `embedding` is filled by the embed step."""

    __tablename__ = "document_chunks"
    __company_id_leading_index__ = True
    __table_args__ = (
        UniqueConstraint("document_id", "ord"),
        Index(None, "company_id", "document_id"),
        Index("ix_document_chunks_tsv", "tsv", postgresql_using="gin"),
        Index(
            "ix_document_chunks_embedding", "embedding", postgresql_using="hnsw",
            postgresql_ops={"embedding": "vector_cosine_ops"},
        ),
    )  # fmt: skip

    document_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE"))
    ord: Mapped[int]
    text: Mapped[str] = mapped_column(Text)
    context: Mapped[str | None] = mapped_column(Text)
    page: Mapped[int | None]
    heading: Mapped[str | None] = mapped_column(String(200))
    embedding: Mapped[Any | None] = mapped_column(Vector(EMBEDDING_DIMENSIONS))
    tsv: Mapped[Any] = mapped_column(TSVECTOR, Computed(_TSV, persisted=True))


class DocumentLink(Base, CompanyScoped):
    """A document belongs to a person, unit, lease or case. `method`: message, exact, fuzzy or owner."""

    __tablename__ = "document_links"
    __company_id_leading_index__ = True
    __table_args__ = (
        UniqueConstraint("document_id", "kind", "ref_id"),
        Index(None, "company_id", "kind", "ref_id"),
    )

    document_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE"))
    kind: Mapped[DocLinkKind] = mapped_column(str_enum(DocLinkKind))
    ref_id: Mapped[uuid.UUID]
    method: Mapped[str] = mapped_column(String(16))
    score: Mapped[float] = mapped_column(Float)


class DriveReorgPlan(Base, CompanyScoped):
    """Owner-approved plan to move Drive files to the current layout. Applied by workflow `drive:reorg:{id}`."""

    __tablename__ = "drive_reorg_plans"
    __company_id_leading_index__ = True
    __table_args__ = (Index(None, "company_id", "status"),)

    status: Mapped[ReorgPlanStatus] = mapped_column(
        str_enum(ReorgPlanStatus), default=ReorgPlanStatus.proposed, server_default=ReorgPlanStatus.proposed.value
    )
    layout_version: Mapped[str] = mapped_column(String(8))
    created_by: Mapped[str] = mapped_column(String(16))  # "owner" | "system"
    applied_at: Mapped[datetime | None]


class DriveReorgItem(Base, CompanyScoped):
    __tablename__ = "drive_reorg_items"
    __company_id_leading_index__ = True
    __table_args__ = (UniqueConstraint("plan_id", "document_id"), Index(None, "company_id", "plan_id"))

    plan_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("drive_reorg_plans.id", ondelete="CASCADE"))
    document_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("documents.id"))
    from_folder: Mapped[str] = mapped_column(String(255))
    to_folder: Mapped[str] = mapped_column(String(255))
    from_name: Mapped[str] = mapped_column(String(255))
    to_name: Mapped[str] = mapped_column(String(255))
    reason: Mapped[str] = mapped_column(String(200))
    status: Mapped[ReorgItemStatus] = mapped_column(
        str_enum(ReorgItemStatus), default=ReorgItemStatus.proposed, server_default=ReorgItemStatus.proposed.value
    )
