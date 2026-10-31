"""Quote checker (spec 2026-10-31): agreed rate cards, decision-day price snapshots, quotes and their reviews."""

import uuid
from datetime import date
from decimal import Decimal
from typing import Any

from sqlalchemy import ForeignKey, Index, Numeric, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.contracts.finance import PriceBasis, SnapshotBasis, Verdict
from app.db.base import Base, CompanyScoped, Validity, str_enum
from app.db.enums import QuoteSource, QuoteStatus, RateSource


class VendorRate(Base, CompanyScoped, Validity):
    """A rate agreed with a contractor (owner entry, extracted from a document, or adopted from a quote)."""

    __tablename__ = "vendor_rates"
    __company_id_leading_index__ = True
    __table_args__ = (
        UniqueConstraint("company_id", "person_id", "item_key", "valid_from"),
        Index("ix_vendor_rates_lookup", "company_id", "person_id", "item_key"),
    )

    person_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("people.id"))
    item_key: Mapped[str] = mapped_column(String(100))
    description: Mapped[str] = mapped_column(String(200))
    unit: Mapped[str] = mapped_column(String(30))
    amount: Mapped[Decimal]
    currency: Mapped[str] = mapped_column(String(3))
    source: Mapped[RateSource] = mapped_column(str_enum(RateSource))
    source_ref: Mapped[str | None] = mapped_column(String(200))


class PriceSnapshot(Base, CompanyScoped):
    """Market prices for one item on the day the owner decided (always tied to the decided action)."""

    __tablename__ = "price_snapshots"
    __company_id_leading_index__ = True
    __table_args__ = (
        UniqueConstraint("company_id", "action_id", "item_key"),
        Index("ix_price_snapshots_company_case", "company_id", "case_id"),
    )

    case_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("cases.id"))
    action_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("actions.id"))
    item_key: Mapped[str] = mapped_column(String(100))
    unit: Mapped[str] = mapped_column(String(30))
    as_of: Mapped[date]
    low: Mapped[Decimal]
    avg: Mapped[Decimal]
    high: Mapped[Decimal]
    sample_count: Mapped[int]
    basis: Mapped[PriceBasis] = mapped_column(str_enum(PriceBasis))
    sources: Mapped[list[Any]] = mapped_column(JSONB, default=list, server_default="[]")
    rate_card_amount: Mapped[Decimal | None]
    rate_card_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("vendor_rates.id"))


class QuoteRow(Base, CompanyScoped):
    """A contractor quote or invoice; `unlinked` until the owner attaches it to a case."""

    __tablename__ = "quotes"
    __company_id_leading_index__ = True
    __table_args__ = (
        UniqueConstraint("company_id", "source", "source_id"),
        Index("ix_quotes_company_case", "company_id", "case_id"),
    )

    case_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("cases.id"))
    person_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("people.id"))
    source: Mapped[QuoteSource] = mapped_column(str_enum(QuoteSource))
    source_id: Mapped[uuid.UUID]
    quote_date: Mapped[date]
    work_date: Mapped[date | None]
    currency: Mapped[str] = mapped_column(String(3))
    total: Mapped[Decimal | None]
    status: Mapped[QuoteStatus] = mapped_column(
        str_enum(QuoteStatus), default=QuoteStatus.received, server_default=QuoteStatus.received.value
    )


class QuoteLineRow(Base, CompanyScoped):
    __tablename__ = "quote_lines"

    quote_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("quotes.id"), index=True)
    position: Mapped[int]
    description: Mapped[str] = mapped_column(String(200))
    item_key: Mapped[str] = mapped_column(String(100))
    quantity: Mapped[Decimal] = mapped_column(Numeric(12, 3))
    unit: Mapped[str] = mapped_column(String(30))
    unit_price: Mapped[Decimal | None]
    amount: Mapped[Decimal]
    vat_included: Mapped[bool | None]


class QuoteReview(Base, CompanyScoped):
    """Append-only: a recheck adds a row, the previous verdict stays as history."""

    __tablename__ = "quote_reviews"

    quote_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("quotes.id"), index=True)
    snapshot_basis: Mapped[SnapshotBasis] = mapped_column(str_enum(SnapshotBasis))
    verdict: Mapped[Verdict] = mapped_column(str_enum(Verdict))
    overcharge: Mapped[Decimal]
    late_days: Mapped[int]
    report: Mapped[dict[str, Any]] = mapped_column(JSONB)
