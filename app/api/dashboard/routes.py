"""Dashboard REST API Routes.

Provides executive pulse indicators, unresponsive radar stalled items, prospective
tenant inquiries, and autonomous background execution logs for the EstateOS Today Dashboard.
"""

from datetime import UTC, datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy import Engine, case, func, or_, select
from sqlalchemy.orm import Session

from app.api.deps import get_engine
from app.api.inbox.summary import safe_name
from app.api.v1.access import require_section
from app.api.v1.auth import Principal, require_session
from app.contracts import CaseState
from app.core.ids import case_ref
from app.core.rent_data import RENT_DATA_AVAILABLE
from app.db.enums import SendStatus
from app.db.models import Approval, Case, Lease, Person, Send, TenantRentPayment, Unit, WaitRow

router = APIRouter(
    prefix="/api/dashboard",
    tags=["dashboard"],
    dependencies=[Depends(require_section("dashboard", also_read=("reports",)))],
)


# ---------------------------------------------------------------------------
# Pydantic Response Models
# ---------------------------------------------------------------------------


class PulseMetricsResponse(BaseModel):
    """Executive pulse metrics for the 3 dashboard pillars and portfolio summary."""

    needsYouCount: int = Field(description="Total action items pending owner decision")
    emergencyCount: int = Field(description="Active emergency incidents requiring immediate dispatch")
    openRentTotalEur: float = Field(description="Total open rent balance for the current billing cycle")
    overdueRentEur: float = Field(description="Total overdue rent balance past grace period")
    overdueTenantsCount: int = Field(description="Count of tenants currently in arrears")
    rentDataAvailable: bool = Field(
        default=False,
        description="False until rent data is mirrored from BRIXX: the rent figures are then 0, not known",
    )
    occupancyPercentage: float = Field(description="Portfolio occupancy percentage (0-100)")
    totalUnits: int = Field(description="Total property units in portfolio")
    occupiedUnits: int = Field(description="Currently leased/occupied units")
    autonomousActionsWeek: int = Field(description="Autonomous actions completed by EstateOS this week")
    hoursSavedWeek: float = Field(description="Estimated management hours saved this week")
    syncedAt: str = Field(description="ISO timestamp of data synchronization")


class StalledWaitItem(BaseModel):
    """Single stalled item awaiting reply from a tenant, contractor, or utility."""

    id: str
    caseRef: str
    ticketNumber: str | None = None
    unitLabel: str
    partyName: str
    partyRole: str
    issueSummary: str
    daysWaiting: int
    chasersSent: int
    proposedActionLabel: str


class RadarResponse(BaseModel):
    """List of stalled items for the Unresponsive Radar card."""

    items: list[StalledWaitItem]
    total: int


class ProspectiveInquiryItem(BaseModel):
    """Prospective tenant inquiry or viewing request lead."""

    id: str
    name: str
    contact: str
    channel: str = Field(description="gmail or whatsapp")
    unit: str
    moveIn: str
    request: str
    qualification: str
    status: str


class InquiriesResponse(BaseModel):
    """List of prospective inquiries for the Today dashboard card."""

    inquiries: list[ProspectiveInquiryItem]
    total: int


class AutonomousActionLogItem(BaseModel):
    """Record of an autonomous background action executed by EstateOS."""

    id: str
    timestamp: str
    actionText: str
    entityRef: str
    tag: str


class LogsResponse(BaseModel):
    """List of autonomous operation logs for the dashboard audit trail card."""

    logs: list[AutonomousActionLogItem]
    total: int


# ---------------------------------------------------------------------------
# API Routes
# ---------------------------------------------------------------------------


def _party_name(party: Person | None, principal: Principal) -> str:
    if party is None:
        return "Whoever answers"
    return party.display_name if principal.access.can("inbox") else safe_name(party.display_name)


OPEN_CASE_STATES = (CaseState.open, CaseState.waiting_on_owner, CaseState.waiting_on_third_party)


@router.get(
    "/pulse",
    dependencies=[Depends(require_section("dashboard"))],
    response_model=PulseMetricsResponse,
    summary="Get Executive Pulse Metrics",
    description=(
        "Counts what needs the owner (pending approvals, emergencies), the company's units and how many have a "
        "current lease. Rent figures are 0 with `rentDataAvailable=false` until rent data is mirrored from BRIXX."
    ),
)
def get_pulse_metrics(
    engine: Annotated[Engine, Depends(get_engine)],
    principal: Annotated[Principal, Depends(require_session)],
) -> PulseMetricsResponse:
    """Returns the executive pulse for the signed-in company. A database error is an error, never made-up numbers."""
    cid = principal.company_id
    now = datetime.now(UTC)
    with Session(engine) as session:
        pending = session.scalar(
            select(func.count(Approval.id)).where(Approval.company_id == cid, Approval.status == "pending")
        )
        emergencies = session.scalar(
            select(func.count(Case.id)).where(
                Case.company_id == cid, Case.urgency == "emergency", Case.state.in_(OPEN_CASE_STATES)
            )
        )
        total_units = session.scalar(select(func.count(Unit.id)).where(Unit.company_id == cid, Unit.valid_to.is_(None)))
        occupied = session.scalar(  # a current lease: started, and open-ended or not yet ended (as the units list)
            select(func.count(func.distinct(Lease.unit_id))).where(
                Lease.company_id == cid,
                Lease.valid_from <= now.date(),
                or_(Lease.valid_to.is_(None), Lease.valid_to >= now.date()),
            )
        )
        sent_week = session.scalar(
            select(func.count(Send.id)).where(
                Send.company_id == cid, Send.status == SendStatus.sent, Send.attempted_at >= now - timedelta(days=7)
            )
        )

        # Query live tenant rent ledger metrics for current/latest billing cycle
        open_rent_eur = 0.0
        overdue_rent_eur = 0.0
        overdue_tenants_cnt = 0
        rent_available = RENT_DATA_AVAILABLE

        latest_billing_month = session.scalar(
            select(func.max(TenantRentPayment.billing_month)).where(TenantRentPayment.company_id == cid)
        )
        if latest_billing_month is not None:
            rent_stats = session.execute(
                select(
                    func.sum(TenantRentPayment.contract_rent_cents),
                    func.sum(
                        case(
                            (
                                TenantRentPayment.status == "overdue",
                                TenantRentPayment.contract_rent_cents - TenantRentPayment.amount_paid_cents,
                            ),
                            else_=0,
                        )
                    ),
                    func.count(
                        case(
                            (TenantRentPayment.status == "overdue", 1),
                        )
                    ),
                ).where(
                    TenantRentPayment.company_id == cid,
                    TenantRentPayment.billing_month == latest_billing_month,
                )
            ).first()
            if rent_stats and rent_stats[0] is not None:
                scheduled_cents = rent_stats[0] or 0
                overdue_cents = rent_stats[1] or 0
                overdue_tenants_cnt = int(rent_stats[2] or 0)
                open_rent_eur = round(float(scheduled_cents) / 100.0, 2)
                overdue_rent_eur = round(float(overdue_cents) / 100.0, 2)
                rent_available = True

    total, leased = total_units or 0, occupied or 0
    return PulseMetricsResponse(
        needsYouCount=pending or 0,
        emergencyCount=emergencies or 0,
        openRentTotalEur=open_rent_eur,
        overdueRentEur=overdue_rent_eur,
        overdueTenantsCount=overdue_tenants_cnt,
        rentDataAvailable=rent_available,
        occupancyPercentage=round(leased / total * 100, 1) if total else 0.0,
        totalUnits=total,
        occupiedUnits=leased,
        autonomousActionsWeek=sent_week or 0,
        hoursSavedWeek=0.0,
        syncedAt=now.isoformat(),
    )


@router.get(
    "/radar",
    dependencies=[Depends(require_section("dashboard"))],
    response_model=RadarResponse,
    summary="Get Unresponsive Cases Radar",
    description=(
        "Lists open waits (someone owes an answer) that are past their expected time, with who, where and how long."
    ),
)
def get_unresponsive_radar(
    engine: Annotated[Engine, Depends(get_engine)],
    principal: Annotated[Principal, Depends(require_session)],
    limit: int = Query(default=10, ge=1, le=50, description="Max items to return"),
) -> RadarResponse:
    cid = principal.company_id
    now = datetime.now(UTC)
    items: list[StalledWaitItem] = []
    with Session(engine) as session:
        rows = session.scalars(
            select(WaitRow)
            .where(WaitRow.company_id == cid, WaitRow.status == "waiting", WaitRow.expected_by <= now)
            .order_by(WaitRow.expected_by.asc())
            .limit(limit)
        ).all()
        for r in rows:
            case = session.scalars(select(Case).where(Case.id == r.case_id, Case.company_id == cid)).first()
            unit = session.get(Unit, case.unit_id) if case is not None and case.unit_id else None
            party = (
                session.scalars(select(Person).where(Person.id == r.party_person_id, Person.company_id == cid)).first()
                if r.party_person_id
                else None
            )
            items.append(
                StalledWaitItem(
                    id=str(r.id),
                    caseRef=f"#cs-{case_ref(r.case_id)}",
                    unitLabel=(unit.address or unit.label) if unit else "",
                    partyName=_party_name(party, principal),
                    partyRole=party.kind.value if party else "",
                    issueSummary=r.about or "Awaiting a response",
                    daysWaiting=max(0, (now - r.expected_by).days),
                    chasersSent=r.chase_count,
                    proposedActionLabel="Send follow-up nudge",
                )
            )
    return RadarResponse(items=items, total=len(items))


@router.get(
    "/inquiries",
    dependencies=[Depends(require_section("dashboard"))],
    response_model=InquiriesResponse,
    summary="Get Prospective Tenant Inquiries",
    description="Prospective tenant leads. Empty until inquiries are captured; EstateOS does not invent leads.",
)
def get_prospective_inquiries() -> InquiriesResponse:
    return InquiriesResponse(inquiries=[], total=0)


@router.get(
    "/logs",
    response_model=LogsResponse,
    summary="Get Autonomous Background Logs",
    description="Recent actions completed by EstateOS: replies sent after the owner approved them.",
)
def get_autonomous_logs(
    engine: Annotated[Engine, Depends(get_engine)],
    principal: Annotated[Principal, Depends(require_session)],
    limit: int = Query(default=5, ge=1, le=20, description="Number of logs to return"),
) -> LogsResponse:
    with Session(engine) as session:
        sends = session.scalars(
            select(Send)
            .where(Send.company_id == principal.company_id, Send.status == SendStatus.sent)
            .order_by(Send.attempted_at.desc())
            .limit(limit)
        ).all()
    logs = [
        AutonomousActionLogItem(
            id=str(snd.id),
            timestamp=snd.attempted_at.astimezone(UTC).strftime("%Y-%m-%d %H:%M UTC") if snd.attempted_at else "",
            actionText=f"Sent an approved {snd.channel.value} reply",
            entityRef=f"#{case_ref(snd.id)}",
            tag="send",
        )
        for snd in sends
    ]
    return LogsResponse(logs=logs, total=len(logs))


class BriefingSection(BaseModel):
    category: str
    headline: str
    details: str
    urgency: str = "normal"


class BriefingResponse(BaseModel):
    headline: str
    summarySentence: str
    sections: list[BriefingSection]
    generatedAt: str


def _plural(count: int, noun: str) -> str:
    return f"{count} {noun}" if count == 1 else f"{count} {noun}s"


@router.get(
    "/briefing",
    dependencies=[Depends(require_section("dashboard"))],
    response_model=BriefingResponse,
    summary="Get Executive Morning Pulse / Weekly Briefing",
    description="A short briefing built only from the company's own counts: urgent cases, pending approvals, cases.",
)
def get_executive_briefing(
    engine: Annotated[Engine, Depends(get_engine)],
    principal: Annotated[Principal, Depends(require_session)],
    kind: str = Query(default="daily", description="daily or weekly"),
) -> BriefingResponse:
    cid = principal.company_id
    now = datetime.now(UTC)
    with Session(engine) as session:
        urgent = session.scalars(
            select(Case)
            .where(Case.company_id == cid, Case.urgency.in_(["emergency", "high"]), Case.state.in_(OPEN_CASE_STATES))
            .order_by(Case.opened_at.desc())
        ).all()
        pending = session.scalar(
            select(func.count(Approval.id)).where(Approval.company_id == cid, Approval.status == "pending")
        )
        open_cases = session.scalar(
            select(func.count(Case.id)).where(Case.company_id == cid, Case.state.in_(OPEN_CASE_STATES))
        )
    pending_n, open_n = pending or 0, open_cases or 0
    top = urgent[0] if urgent else None
    top_title = (top.summary or "Urgent case") if top else "Nothing urgent"
    top_detail = (
        f"Case state: {top.state.value}. Category: {top.category.value}." if top else "No urgent cases are open."
    )
    weekly = kind == "weekly"
    return BriefingResponse(
        headline=(
            f"Weekly review: {_plural(open_n, 'open case')}, {_plural(len(urgent), 'urgent matter')}."
            if weekly
            else f"Morning pulse: {_plural(len(urgent), 'matter')} need attention; "
            f"{_plural(pending_n, 'draft')} awaiting your review."
        ),
        summarySentence=(
            f"{_plural(pending_n, 'decision')} waiting on you." if weekly else f"{top_title}. {pending_n} in the inbox."
        ),
        sections=[
            BriefingSection(
                category="Urgent triage",
                headline=top_title,
                details=top_detail,
                urgency="emergency" if urgent else "normal",
            ),
            BriefingSection(
                category="Pending approvals",
                headline=f"{_plural(pending_n, 'draft')} awaiting review",
                details="Review and approve them in the inbox; nothing is sent until you do.",
                urgency="high" if pending_n else "normal",
            ),
            BriefingSection(
                category="Operations",
                headline=f"{_plural(open_n, 'open case')}",
                details="Counted from the cases in the system.",
            ),
        ],
        generatedAt=now.isoformat(),
    )
