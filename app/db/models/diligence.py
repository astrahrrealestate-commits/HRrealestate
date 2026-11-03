"""Due Diligence Lite (spec 2026-10-31): reviews of a pile of property documents, and the cached reads they use."""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import ForeignKey, Index, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.contracts.diligence import DDPropertyKind
from app.contracts.diligence_report import DDVerdict
from app.db.base import Base, CompanyScoped, str_enum
from app.db.enums import DDReviewStatus


class DDReview(Base, CompanyScoped):
    """One screening of a set of documents. `report` holds the `DDReport` once `status` is `done`; a rerun bumps
    `run_no` (workflow id `dd:{id}:{run_no}`) and overwrites it."""

    __tablename__ = "dd_reviews"
    __company_id_leading_index__ = True
    __table_args__ = (Index(None, "company_id", "created_at"),)

    title: Mapped[str] = mapped_column(String(200))
    property_kind: Mapped[DDPropertyKind] = mapped_column(str_enum(DDPropertyKind))
    unit_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("units.id"), index=True)  # 0030
    status: Mapped[DDReviewStatus] = mapped_column(
        str_enum(DDReviewStatus), default=DDReviewStatus.pending, server_default=DDReviewStatus.pending.value
    )
    run_no: Mapped[int] = mapped_column(default=1, server_default="1")
    framework_version: Mapped[str | None] = mapped_column(String(32))
    verdict: Mapped[DDVerdict | None] = mapped_column(str_enum(DDVerdict))
    report: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    error: Mapped[str | None] = mapped_column(Text)
    completed_at: Mapped[datetime | None]


class DDReviewDocument(Base, CompanyScoped):
    __tablename__ = "dd_review_documents"
    __company_id_leading_index__ = True
    __table_args__ = (
        UniqueConstraint("review_id", "document_id"),
        Index("ix_dd_review_documents_review", "company_id", "review_id"),
    )

    review_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("dd_reviews.id", ondelete="CASCADE"))
    document_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("documents.id"))


class DDDocumentRead(Base, CompanyScoped):
    """The verified `DDDocRead` of one document by one reader version. Reused by every review that includes the
    document, so a rerun reads only new documents."""

    __tablename__ = "dd_document_reads"
    __company_id_leading_index__ = True
    __table_args__ = (UniqueConstraint("company_id", "document_id", "reader_version"),)

    document_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("documents.id"))
    reader_version: Mapped[str] = mapped_column(String(32))
    read: Mapped[dict[str, Any]] = mapped_column(JSONB)
    unverified: Mapped[int] = mapped_column(default=0, server_default="0")  # claims and flags dropped at verification
