"""Calendar event model for appointments, inspections, and contractor visits."""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import ForeignKey, Index, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, CompanyScoped


class CalendarEventRow(Base, CompanyScoped):
    """Calendar event tracking scheduled and proposed property visits."""

    __tablename__ = "calendar_events"
    __company_id_leading_index__ = True
    __table_args__ = (
        Index(None, "company_id", "status"),
        Index(None, "start_time", "end_time"),
    )

    case_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("cases.id"), index=True)
    unit_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("units.id"), index=True)
    title: Mapped[str] = mapped_column(String(200))
    description: Mapped[str | None] = mapped_column(Text)
    start_time: Mapped[datetime] = mapped_column(index=True)
    end_time: Mapped[datetime] = mapped_column(index=True)
    status: Mapped[str] = mapped_column(String(32), default="proposed", server_default="proposed", index=True)
    event_type: Mapped[str] = mapped_column(String(32), default="contractor_repair", server_default="contractor_repair")
    external_event_id: Mapped[str | None] = mapped_column(String(128))
    location: Mapped[str | None] = mapped_column(String(255))
    attendees: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list, server_default="[]")
    lockbox_code: Mapped[str | None] = mapped_column(String(32))
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    confirmed_at: Mapped[datetime | None] = mapped_column(default=None)

