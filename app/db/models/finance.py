"""Quote checker (spec 2026-10-31): agreed rate cards, decision-day price snapshots, quotes and their reviews."""

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import BigInteger, Date, DateTime, ForeignKey, Index, Integer, Numeric, String, Text, UniqueConstraint
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


class TenantRentPayment(Base, CompanyScoped):
    """Monthly rent tracking per tenant and unit with contract rent, paid timestamps, and overdue status."""

    __tablename__ = "tenant_rent_payments"
    __company_id_leading_index__ = True
    __table_args__ = (
        UniqueConstraint("company_id", "lease_id", "billing_month", name="uq_tenant_monthly_rent"),
        Index("ix_rent_company_month", "company_id", "billing_month"),
        Index("ix_rent_status", "company_id", "status"),
        Index("ix_rent_tenant", "company_id", "tenant_id"),
    )

    invoice_number: Mapped[str] = mapped_column(String(64), index=True)
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("people.id"), index=True)
    unit_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("units.id"), index=True)
    lease_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("leases.id"), index=True)

    billing_month: Mapped[date] = mapped_column(Date)  # First day of the cycle month e.g. 2026-11-01
    contract_rent_cents: Mapped[int] = mapped_column(BigInteger)  # Euro cents e.g. 185000 for €1,850.00
    amount_paid_cents: Mapped[int] = mapped_column(BigInteger, default=0, server_default="0")

    due_date: Mapped[date] = mapped_column(Date)
    paid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    status: Mapped[str] = mapped_column(String(20), default="pending", server_default="pending")  # paid, pending, overdue, partial
    overdue_days: Mapped[int] = mapped_column(Integer, default=0, server_default="0")

    payment_method: Mapped[str] = mapped_column(String(50), default="SEPA Direct Debit", server_default="SEPA Direct Debit")
    transaction_reference: Mapped[str | None] = mapped_column(String(100), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)


class MonthlyRentSummary(Base, CompanyScoped):
    """Pre-aggregated monthly rent rollups for fast month-over-month comparisons and charting."""

    __tablename__ = "monthly_rent_summaries"
    __company_id_leading_index__ = True
    __table_args__ = (
        UniqueConstraint("company_id", "billing_month", name="uq_monthly_rent_summary"),
        Index("ix_rent_summary_month", "company_id", "billing_month"),
    )

    billing_month: Mapped[date] = mapped_column(Date)  # First day of the month e.g. 2026-11-01
    total_scheduled_rent_cents: Mapped[int] = mapped_column(BigInteger)
    total_collected_rent_cents: Mapped[int] = mapped_column(BigInteger)
    total_overdue_rent_cents: Mapped[int] = mapped_column(BigInteger)

    total_tenants_count: Mapped[int] = mapped_column(Integer)
    paid_tenants_count: Mapped[int] = mapped_column(Integer)
    overdue_tenants_count: Mapped[int] = mapped_column(Integer)
    collection_rate_pct: Mapped[Decimal] = mapped_column(Numeric(5, 2))

