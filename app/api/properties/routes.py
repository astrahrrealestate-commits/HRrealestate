"""Properties REST API Routes.

Feeds the portfolio directory (units, occupancy, tenant and lease end) to the Next.js frontend from the company's own
directory tables. Rent amounts and lockbox codes are not stored there yet, so they are not reported: the rent is 0.0
(unknown, see `rentDataAvailable` on the dashboard pulse) and no lockbox code is ever returned.
"""

from datetime import UTC, date, datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import Engine, func, select
from sqlalchemy.orm import Session

from app.api.deps import get_engine
from app.api.v1.access import require_section
from app.api.v1.auth import Principal, require_session
from app.contracts import CaseState, Channel
from app.db.models import Case, ChannelIdentity, Lease, LeaseParty, Person, Unit
from app.db.models.finance import TenantRentPayment

router = APIRouter(
    prefix="/api/properties",
    tags=["properties"],
    dependencies=[Depends(require_section("properties", also_read=("reports", "dashboard")))],
)


class UnitItem(BaseModel):
    """Single property unit in the portfolio."""

    id: str
    label: str = Field(description="Unit identifier e.g. Pieter Floriszstraat 1 C")
    address: str
    buildingName: str
    status: str = Field(description="occupied, vacant, notice_given")
    monthlyRentEur: float
    currentTenant: str | None = None
    tenantPhone: str | None = None
    tenantEmail: str | None = None
    leaseStart: str | None = None
    leaseEnd: str | None = None
    lockboxCode: str | None = None
    floor: str | None = None
    livingAreaSqm: int | None = None
    depositEur: float | None = None
    rentStatus: str | None = None
    activeTicketCount: int = 0


class PropertiesResponse(BaseModel):
    """List of property units and aggregate summary counts."""

    totalUnits: int
    occupiedCount: int
    vacantCount: int
    units: list[UnitItem]


def _status(lease_end: date | None, today: date) -> str:
    if lease_end is None:
        return "occupied"
    if lease_end < today:
        return "vacant"
    if (lease_end - today).days <= 30:
        return "notice_given"
    return "occupied"


def _for_viewer(item: UnitItem, principal: Principal) -> UnitItem:
    """The tenant's phone and email belong to the Tenants section (ADR 0012); Properties alone sees the unit."""
    if principal.access.can("tenants"):
        return item
    return item.model_copy(update={"tenantPhone": None, "tenantEmail": None})


def _item(session: Session, unit: Unit, today: date) -> UnitItem:
    """The unit with its current lease: one that has not ended (open-ended, or ending today or later)."""
    lease = session.scalars(
        select(Lease)
        .where(
            Lease.company_id == unit.company_id,
            Lease.unit_id == unit.id,
            (Lease.valid_to.is_(None)) | (Lease.valid_to >= today),
            Lease.valid_from <= today,
        )
        .order_by(Lease.valid_from.desc())
    ).first()
    tenant = None
    tenant_phone = None
    tenant_email = None
    monthly_rent = 0.0
    rent_status = None

    if lease is not None:
        tenant = session.scalars(
            select(Person)
            .join(LeaseParty, LeaseParty.person_id == Person.id)
            .where(
                LeaseParty.company_id == unit.company_id,
                LeaseParty.lease_id == lease.id,
                LeaseParty.role == "tenant",
            )
        ).first()

        if tenant is not None:
            identities = session.scalars(
                select(ChannelIdentity).where(
                    ChannelIdentity.company_id == unit.company_id,
                    ChannelIdentity.person_id == tenant.id,
                    ChannelIdentity.valid_to.is_(None),
                )
            ).all()
            tenant_phone = next((i.identity for i in identities if i.channel == Channel.whatsapp), None)
            tenant_email = next((i.identity for i in identities if i.channel == Channel.gmail), None)

            rent_record = session.scalars(
                select(TenantRentPayment)
                .where(
                    TenantRentPayment.company_id == unit.company_id,
                    TenantRentPayment.unit_id == unit.id,
                )
                .order_by(TenantRentPayment.billing_month.desc())
            ).first()
            if rent_record:
                monthly_rent = float(rent_record.contract_rent_cents) / 100.0
                rent_status = "overdue" if rent_record.status == "overdue" else "up_to_date"

    open_tickets = (
        session.scalar(
            select(func.count(Case.id)).where(
                Case.company_id == unit.company_id,
                Case.unit_id == unit.id,
                Case.state != CaseState.resolved,
            )
        )
        or 0
    )

    return UnitItem(
        id=str(unit.id),
        label=unit.label,
        address=unit.address or unit.label,
        buildingName="",
        status="vacant" if lease is None else _status(lease.valid_to, today),
        monthlyRentEur=monthly_rent if lease is not None else 0.0,
        currentTenant=tenant.display_name if tenant else None,
        tenantPhone=tenant_phone,
        tenantEmail=tenant_email,
        leaseStart=f"{lease.valid_from:%d-%m-%Y}" if lease is not None and lease.valid_from else None,
        leaseEnd=f"{lease.valid_to:%d-%m-%Y}" if lease is not None and lease.valid_to else None,
        lockboxCode=None,
        rentStatus=rent_status,
        activeTicketCount=open_tickets,
    )


@router.get(
    "",
    response_model=PropertiesResponse,
    summary="Get Portfolio Properties & Units",
    description="The company's units with occupancy status, address, current tenant and lease end.",
)
def get_properties(
    engine: Annotated[Engine, Depends(get_engine)],
    principal: Annotated[Principal, Depends(require_session)],
    status: str = Query(default="all", description="all, occupied, vacant, notice_given"),
) -> PropertiesResponse:
    today = datetime.now(UTC).date()
    with Session(engine) as session:
        units = session.scalars(
            select(Unit)
            .where(Unit.company_id == principal.company_id, Unit.valid_to.is_(None))
            .order_by(Unit.label.asc())
        ).all()
        items = [_for_viewer(_item(session, unit, today), principal) for unit in units]
    occupied = sum(i.status in ("occupied", "notice_given") for i in items)
    shown = items if status == "all" else [i for i in items if i.status == status]
    return PropertiesResponse(
        totalUnits=len(items), occupiedCount=occupied, vacantCount=len(items) - occupied, units=shown
    )


@router.get(
    "/{unit_id}",
    response_model=UnitItem,
    summary="Get Specific Unit Details",
    description="One of the company's units with its current lease.",
)
def get_unit_details(
    unit_id: str,
    engine: Annotated[Engine, Depends(get_engine)],
    principal: Annotated[Principal, Depends(require_session)],
) -> UnitItem:
    try:
        wanted = UUID(unit_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="Unit not found") from None
    with Session(engine) as session:
        unit = session.scalars(select(Unit).where(Unit.id == wanted, Unit.company_id == principal.company_id)).first()
        if unit is None:
            raise HTTPException(status_code=404, detail="Unit not found")
        return _for_viewer(_item(session, unit, datetime.now(UTC).date()), principal)
