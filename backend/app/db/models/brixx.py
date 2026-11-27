"""BRIXX data mirror bookkeeping (public schema, not `brixx`): sync runs, per-table state, downloaded documents."""

import uuid
from datetime import datetime

from sqlalchemy import BigInteger, ForeignKey, Index, String, Text, UniqueConstraint, false, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, CompanyScoped, str_enum
from app.db.enums import BrixxDocumentStatus, BrixxRunKind, BrixxRunStatus


class BrixxSyncRun(Base, CompanyScoped):
    """One incremental or reconcile pass over the BRIXX tables."""

    __tablename__ = "brixx_sync_runs"
    __company_id_leading_index__ = True
    __table_args__ = (Index("ix_brixx_sync_runs_company_started", "company_id", "started_at"),)

    kind: Mapped[BrixxRunKind] = mapped_column(str_enum(BrixxRunKind))
    status: Mapped[BrixxRunStatus] = mapped_column(
        str_enum(BrixxRunStatus), default=BrixxRunStatus.running, server_default=BrixxRunStatus.running.value
    )
    started_at: Mapped[datetime]
    finished_at: Mapped[datetime | None]
    error: Mapped[str | None] = mapped_column(Text)


class BrixxSyncTableState(Base, CompanyScoped):
    """Resume point and health of one mirrored table; `last_success_upd` is the incremental watermark."""

    __tablename__ = "brixx_sync_table_state"
    __company_id_leading_index__ = True
    __table_args__ = (UniqueConstraint("company_id", "table_name"),)

    table_name: Mapped[str] = mapped_column(String(128))
    last_success_upd: Mapped[datetime | None]
    last_page: Mapped[int] = mapped_column(default=0, server_default="0")
    row_count: Mapped[int] = mapped_column(default=0, server_default="0")
    last_error: Mapped[str | None] = mapped_column(Text)
    drifted: Mapped[bool] = mapped_column(default=False, server_default=false())
    last_run_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("brixx_sync_runs.id", ondelete="SET NULL"))


class BrixxDocument(Base, CompanyScoped):
    """One version of a BRIXX `PRG_DOCUMENT` file and where its bytes are stored.

    `source_version` is the mirror row's version marker when the download was claimed (one row per version). Stored
    content is unique per `(company_id, document_id, sha256)`: a new version with the same bytes moves that row to the
    new version instead of storing a second object. `last_error` holds an error class name only.
    """

    __tablename__ = "brixx_documents"
    __company_id_leading_index__ = True
    __table_args__ = (
        UniqueConstraint("company_id", "document_id", "sha256"),
        UniqueConstraint("company_id", "document_id", "source_version"),
    )

    document_id: Mapped[int] = mapped_column(BigInteger)
    source_version: Mapped[str] = mapped_column(String(128))
    status: Mapped[BrixxDocumentStatus] = mapped_column(
        str_enum(BrixxDocumentStatus),
        default=BrixxDocumentStatus.pending,
        server_default=BrixxDocumentStatus.pending.value,
    )
    sha256: Mapped[str | None] = mapped_column(String(64))
    storage_key: Mapped[str | None] = mapped_column(Text)
    size_bytes: Mapped[int | None] = mapped_column(BigInteger)
    content_type: Mapped[str | None] = mapped_column(String(255))
    attempts: Mapped[int] = mapped_column(default=0, server_default="0")
    last_error: Mapped[str | None] = mapped_column(String(128))
    ocr_attempts: Mapped[int] = mapped_column(default=0, server_default="0")  # failed vision reads of a scan (M13)
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now(), onupdate=func.now())
