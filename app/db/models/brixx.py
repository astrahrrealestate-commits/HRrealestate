"""BRIXX data mirror bookkeeping: one row per sync run and one per mirrored table (public schema, not `brixx`)."""

import uuid
from datetime import datetime

from sqlalchemy import ForeignKey, Index, String, Text, UniqueConstraint, false
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, CompanyScoped, str_enum
from app.db.enums import BrixxRunKind, BrixxRunStatus


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
