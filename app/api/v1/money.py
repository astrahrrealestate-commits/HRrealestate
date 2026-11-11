"""Tenant Rent & Collections Ledger API.

Dedicated exclusively to tenant rent management, overdue tracking,
and Month-over-Month (MoM) collection analytics.
"""

from datetime import date, datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import Engine, case, distinct, func, or_, select
from sqlalchemy.orm import Session

from app.api.deps import get_engine
from app.api.v1.access import require_section
from app.api.v1.auth import Principal, require_session
from app.contracts import Channel
from app.core.logging import get_logger
from app.db.models.directory import ChannelIdentity, Person, Unit
from app.db.models.finance import MonthlyRentSummary, TenantRentPayment

router = APIRouter(prefix="/money", tags=["money"], dependencies=[Depends(require_section("money"))])
log = get_logger(__name__)

SessionPrincipal = Annotated[Principal, Depends(require_session)]
EngineDep = Annotated[Engine, Depends(get_engine)]

MONTH_NAMES = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


# ---------------------------------------------------------------------------
# Pydantic Schemas
# ---------------------------------------------------------------------------


class RentLedgerItem(BaseModel):
    id: str
    invoiceNumber: str
    tenantId: str
    tenantName: str
    tenantEmail: str | None = None
    tenantPhone: str | None = None
    unitId: str
    unitLabel: str
    unitAddress: str | None = None
    leaseId: str
    billingMonth: str  # e.g. "2026-11"
    contractRentEur: float
    amountPaidEur: float
    dueDate: str  # formatted "01-11-2026"
    paidAt: str | None = None  # formatted "01 Nov 09:12"
    paidAtIso: str | None = None
    status: str  # "paid" | "overdue" | "pending" | "partial"
    overdueDays: int
    paymentMethod: str
    transactionReference: str | None = None
    notes: str | None = None
    aiSuggestedAction: str | None = None


class RentLedgerResponse(BaseModel):
    items: list[RentLedgerItem]
    totalCount: int
    month: str
    availableMonths: list[str]
    totalScheduledEur: float
    totalCollectedEur: float
    totalOverdueEur: float
    overdueCount: int
    collectionRatePct: float


class MonthAnalytics(BaseModel):
    billingMonth: str
    totalScheduled: float
    totalCollected: float
    totalOverdue: float
    totalTenants: int
    paidTenants: int
    overdueCount: int
    collectionRate: float
    occupiedUnits: int = 110
    totalUnits: int = 110
    occupancyRate: float = 100.0


class PreviousMonthAnalytics(BaseModel):
    billingMonth: str
    totalCollected: float
    collectionRate: float
    momChangePct: float
    occupancyRate: float = 100.0


class HistoricalTrendPoint(BaseModel):
    month: str  # "Jun", "Jul", etc.
    billingMonth: str  # "2026-06"
    scheduled: float
    collected: float
    overdue: float
    rate: float
    occupiedUnits: int
    totalUnits: int = 110
    occupancyRate: float


class RentAnalyticsResponse(BaseModel):
    currentMonth: MonthAnalytics
    previousMonth: PreviousMonthAnalytics | None = None
    historicalTrend: list[HistoricalTrendPoint]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _parse_month(month_str: str | None, default_date: date) -> date:
    if not month_str:
        return default_date
    try:
        parts = month_str.strip().split("-")
        return date(int(parts[0]), int(parts[1]), 1)
    except Exception:
        return default_date


def _format_paid_at(dt: datetime | None) -> str | None:
    if not dt:
        return None
    # e.g. "01 Nov 09:12"
    month_name = MONTH_NAMES[dt.month - 1]
    return f"{dt.day:02d} {month_name} {dt.strftime('%H:%M')}"


# ---------------------------------------------------------------------------
# API Routes
# ---------------------------------------------------------------------------


@router.get(
    "/rent-ledger",
    response_model=RentLedgerResponse,
    summary="Get Tenant Rent Ledger",
    description="List rent payment rows strictly for tenants and units with status, timestamps, and contract amounts.",
)
def get_rent_ledger(
    engine: EngineDep,
    principal: SessionPrincipal,
    month: str | None = Query(default=None, description="Billing month in YYYY-MM format"),
    status: str = Query(default="all", description="Filter by status: all, paid, overdue, pending"),
    search: str | None = Query(default=None, description="Filter by tenant name, unit or invoice reference"),
) -> RentLedgerResponse:
    cid = principal.company_id

    with Session(engine) as session:
        # 1. Discover available months
        avail_stmt = (
            select(distinct(TenantRentPayment.billing_month))
            .where(TenantRentPayment.company_id == cid)
            .order_by(TenantRentPayment.billing_month.desc())
        )
        avail_dates = session.scalars(avail_stmt).all()
        avail_months = [d.strftime("%Y-%m") for d in avail_dates]

        # Determine target billing month
        default_month_date = avail_dates[0] if avail_dates else date(2026, 11, 1)
        target_date = _parse_month(month, default_month_date)

        # 2. Query tenant payments for target month
        stmt = (
            select(TenantRentPayment, Person, Unit)
            .join(Person, TenantRentPayment.tenant_id == Person.id)
            .join(Unit, TenantRentPayment.unit_id == Unit.id)
            .where(
                TenantRentPayment.company_id == cid,
                TenantRentPayment.billing_month == target_date,
            )
        )

        if status and status.lower() != "all":
            stmt = stmt.where(TenantRentPayment.status == status.lower())

        if search and search.strip():
            term = f"%{search.strip().lower()}%"
            stmt = stmt.where(
                or_(
                    func.lower(Person.display_name).like(term),
                    func.lower(Unit.label).like(term),
                    func.lower(Unit.address).like(term),
                    func.lower(TenantRentPayment.invoice_number).like(term),
                )
            )

        # Order: overdue first, then due_date, then invoice
        order_case = case((TenantRentPayment.status == "overdue", 0), else_=1)
        stmt = stmt.order_by(order_case, TenantRentPayment.due_date.asc(), TenantRentPayment.invoice_number.asc())

        results = session.execute(stmt).all()

        # Batch lookup channels (phone & email) for tenants
        tenant_ids = [r[0].tenant_id for r in results]
        identities_map: dict[UUID, dict[str, str]] = {}
        if tenant_ids:
            ident_rows = session.scalars(
                select(ChannelIdentity).where(
                    ChannelIdentity.company_id == cid,
                    ChannelIdentity.person_id.in_(tenant_ids),
                )
            ).all()
            for ident in ident_rows:
                entry = identities_map.setdefault(ident.person_id, {})
                if ident.channel == Channel.whatsapp and "phone" not in entry:
                    entry["phone"] = ident.identity
                elif ident.channel == Channel.gmail and "email" not in entry:
                    entry["email"] = ident.identity

        items: list[RentLedgerItem] = []
        total_scheduled_cents = 0
        total_collected_cents = 0
        total_overdue_cents = 0
        overdue_count = 0

        for payment, person, unit in results:
            total_scheduled_cents += payment.contract_rent_cents
            total_collected_cents += payment.amount_paid_cents
            if payment.status == "overdue":
                total_overdue_cents += payment.contract_rent_cents - payment.amount_paid_cents
                overdue_count += 1

            idents = identities_map.get(person.id, {})
            # AI suggestion based on context
            if payment.status == "overdue":
                if "leak" in (payment.notes or "").lower() or "repair" in (payment.notes or "").lower():
                    ai_act = "Dispatch formal WhatsApp payment link & reference open repair status"
                else:
                    ai_act = "Send 1-click WhatsApp payment reminder with iDEAL payment link"
            elif payment.status == "paid":
                ai_act = "Settled on time via direct debit mandate"
            else:
                ai_act = "Scheduled for settlement on cycle due date"

            items.append(
                RentLedgerItem(
                    id=str(payment.id),
                    invoiceNumber=payment.invoice_number,
                    tenantId=str(person.id),
                    tenantName=person.display_name,
                    tenantEmail=idents.get("email"),
                    tenantPhone=idents.get("phone"),
                    unitId=str(unit.id),
                    unitLabel=unit.label,
                    unitAddress=unit.address,
                    leaseId=str(payment.lease_id),
                    billingMonth=payment.billing_month.strftime("%Y-%m"),
                    contractRentEur=round(float(payment.contract_rent_cents) / 100.0, 2),
                    amountPaidEur=round(float(payment.amount_paid_cents) / 100.0, 2),
                    dueDate=payment.due_date.strftime("%d-%m-%Y"),
                    paidAt=_format_paid_at(payment.paid_at),
                    paidAtIso=payment.paid_at.isoformat() if payment.paid_at else None,
                    status=payment.status,
                    overdueDays=payment.overdue_days,
                    paymentMethod=payment.payment_method,
                    transactionReference=payment.transaction_reference,
                    notes=payment.notes,
                    aiSuggestedAction=ai_act,
                )
            )

        coll_rate = (
            round((float(total_collected_cents) / float(total_scheduled_cents)) * 100.0, 2)
            if total_scheduled_cents > 0
            else 0.0
        )

        return RentLedgerResponse(
            items=items,
            totalCount=len(items),
            month=target_date.strftime("%Y-%m"),
            availableMonths=avail_months,
            totalScheduledEur=round(float(total_scheduled_cents) / 100.0, 2),
            totalCollectedEur=round(float(total_collected_cents) / 100.0, 2),
            totalOverdueEur=round(float(total_overdue_cents) / 100.0, 2),
            overdueCount=overdue_count,
            collectionRatePct=coll_rate,
        )


@router.get(
    "/analytics",
    response_model=RentAnalyticsResponse,
    summary="Get Rent Collections Analytics",
    description="Returns current vs previous month rent aggregates and 6-month historical trend for charting.",
)
def get_rent_analytics(
    engine: EngineDep,
    principal: SessionPrincipal,
) -> RentAnalyticsResponse:
    cid = principal.company_id

    with Session(engine) as session:
        summaries = session.scalars(
            select(MonthlyRentSummary)
            .where(MonthlyRentSummary.company_id == cid)
            .order_by(MonthlyRentSummary.billing_month.asc())
        ).all()

        if not summaries:
            raise HTTPException(status_code=404, detail="no rent analytics recorded")

        # The company's current units: occupancy is tenants paying over the units that exist, not a fixed number.
        total_units = (
            session.scalar(select(func.count(Unit.id)).where(Unit.company_id == cid, Unit.valid_to.is_(None))) or 0
        )
        portfolio_units = max(total_units, 1)
        trend: list[HistoricalTrendPoint] = [
            HistoricalTrendPoint(
                month=MONTH_NAMES[s.billing_month.month - 1],
                billingMonth=s.billing_month.strftime("%Y-%m"),
                scheduled=round(float(s.total_scheduled_rent_cents) / 100.0, 2),
                collected=round(float(s.total_collected_rent_cents) / 100.0, 2),
                overdue=round(float(s.total_overdue_rent_cents) / 100.0, 2),
                rate=float(s.collection_rate_pct),
                occupiedUnits=s.total_tenants_count,
                totalUnits=portfolio_units,
                occupancyRate=round((float(s.total_tenants_count) / float(portfolio_units)) * 100.0, 1),
            )
            for s in summaries
        ]

        current_summary = summaries[-1]
        previous_summary = summaries[-2] if len(summaries) >= 2 else None

        mom_change = 0.0
        if previous_summary and previous_summary.total_collected_rent_cents > 0:
            diff = float(current_summary.total_collected_rent_cents - previous_summary.total_collected_rent_cents)
            mom_change = round((diff / float(previous_summary.total_collected_rent_cents)) * 100.0, 2)

        prev_out = (
            PreviousMonthAnalytics(
                billingMonth=previous_summary.billing_month.strftime("%Y-%m"),
                totalCollected=round(float(previous_summary.total_collected_rent_cents) / 100.0, 2),
                collectionRate=float(previous_summary.collection_rate_pct),
                momChangePct=mom_change,
                occupancyRate=round((float(previous_summary.total_tenants_count) / float(portfolio_units)) * 100.0, 1),
            )
            if previous_summary
            else None
        )

        curr_out = MonthAnalytics(
            billingMonth=current_summary.billing_month.strftime("%Y-%m"),
            totalScheduled=round(float(current_summary.total_scheduled_rent_cents) / 100.0, 2),
            totalCollected=round(float(current_summary.total_collected_rent_cents) / 100.0, 2),
            totalOverdue=round(float(current_summary.total_overdue_rent_cents) / 100.0, 2),
            totalTenants=current_summary.total_tenants_count,
            paidTenants=current_summary.paid_tenants_count,
            overdueCount=current_summary.overdue_tenants_count,
            collectionRate=float(current_summary.collection_rate_pct),
            occupiedUnits=current_summary.total_tenants_count,
            totalUnits=portfolio_units,
            occupancyRate=round((float(current_summary.total_tenants_count) / float(portfolio_units)) * 100.0, 1),
        )

        return RentAnalyticsResponse(
            currentMonth=curr_out,
            previousMonth=prev_out,
            historicalTrend=trend,
        )
