"""Operational tables: due-work timers, draft outcomes, LLM call log, daily quality metrics."""

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import ForeignKey, Index, Numeric, String, Text, UniqueConstraint, false
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, CompanyScoped, str_enum
from app.db.enums import OutcomeLabel, OutcomeSource, TimerStatus


class Timer(Base, CompanyScoped):
    """Due work swept every minute (`FOR UPDATE SKIP LOCKED`). Long waits live here, never in sleeping workflows."""

    __tablename__ = "timers"
    __company_id_leading_index__ = True
    __table_args__ = (Index(None, "status", "due_at"), UniqueConstraint("company_id", "dedupe_key"))

    kind: Mapped[str] = mapped_column(String(64))
    due_at: Mapped[datetime]
    payload: Mapped[dict[str, Any]]
    status: Mapped[TimerStatus] = mapped_column(
        str_enum(TimerStatus), default=TimerStatus.pending, server_default=TimerStatus.pending.value
    )
    attempts: Mapped[int] = mapped_column(default=0, server_default="0")
    locked_until: Mapped[datetime | None]
    dedupe_key: Mapped[str] = mapped_column(String(255))  # unique per company


class Outcome(Base, CompanyScoped):
    __tablename__ = "outcomes"
    __table_args__ = (UniqueConstraint("action_id", "draft_version"),)  # one captured outcome per sent draft

    action_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("actions.id"), index=True)
    draft_version: Mapped[int]
    final_text: Mapped[str] = mapped_column(Text)
    label: Mapped[OutcomeLabel] = mapped_column(str_enum(OutcomeLabel))
    similarity: Mapped[float | None]
    source: Mapped[OutcomeSource] = mapped_column(str_enum(OutcomeSource))


class ModelCall(Base, CompanyScoped):
    __tablename__ = "model_calls"
    __company_id_leading_index__ = True
    __table_args__ = (Index(None, "company_id", "created_at"),)

    purpose: Mapped[str] = mapped_column(String(64))
    prompt_name: Mapped[str] = mapped_column(String(64))
    prompt_version: Mapped[str] = mapped_column(String(16))
    prompt_sha256: Mapped[str] = mapped_column(String(64))
    model: Mapped[str] = mapped_column(String(128))
    input: Mapped[dict[str, Any]]
    output: Mapped[dict[str, Any] | None]
    tokens_in: Mapped[int | None]
    tokens_cached: Mapped[int | None]
    tokens_out: Mapped[int | None]
    cost_usd: Mapped[Decimal | None] = mapped_column(Numeric(10, 6))
    latency_ms: Mapped[int | None]
    prefix_hash: Mapped[str | None] = mapped_column(String(64))
    langfuse_trace_id: Mapped[str | None] = mapped_column(String(64))
    error: Mapped[str | None] = mapped_column(Text)


class MetricSnapshot(Base, CompanyScoped):
    """One quality/cost/performance metric per company-day (#8 drift monitor)."""

    __tablename__ = "metric_snapshots"
    __company_id_leading_index__ = True
    __table_args__ = (UniqueConstraint("company_id", "day", "metric"),)

    day: Mapped[date]
    metric: Mapped[str] = mapped_column(String(64))
    value: Mapped[float]
    baseline: Mapped[float | None]
    breached: Mapped[bool] = mapped_column(default=False, server_default=false())
