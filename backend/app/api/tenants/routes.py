"""Tenants REST API Routes.

Feeds the tenant directory (contact details, unit, lease dates) to the Next.js frontend from the company's own
directory tables. Rent amounts and payment status are not stored there yet, so the rent is 0.0 and the status is
`unknown` rather than a guess; arrears arrive with the BRIXX rent mirror.
"""

from datetime import UTC, date, datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from app.api.deps import get_engine
from app.api.v1.access import require_section
from app.api.v1.auth import Principal, require_session
from app.contracts import Channel
from app.db.enums import PersonKind
from app.db.models import ChannelIdentity, Lease, LeaseParty, Person, Unit
from app.db.models.finance import TenantRentPayment
from app.directory.brixx.unit_facts import UnitFacts, unit_facts

router = APIRouter(
    prefix="/api/tenants",
    tags=["tenants"],
    dependencies=[Depends(require_section("tenants", also_read=("reports", "dashboard")))],
)

RENT_UNKNOWN = "unknown"


class TenantItem(BaseModel):
    """Single tenant record with active lease and contact details."""

    id: str
    name: str
    phone: str
    email: str
    unitLabel: str
    leaseStart: str
    leaseEnd: str
    monthlyRentEur: float
    rentStatus: str = Field(description="up_to_date, grace_period, overdue, or unknown when no rent data is mirrored")
    overdueDays: int = 0


class TenantsResponse(BaseModel):
    """List of active tenants and portfolio rent statistics."""

    totalTenants: int
    overdueCount: int
    tenants: list[TenantItem]


def _without_contact(tenant: TenantItem) -> TenantItem:
    """What Reports and Dashboard see: the rent roll, not the tenant's phone and email (ADR 0012)."""
    return tenant.model_copy(update={"phone": "", "email": ""})


def _item(session: Session, person: Person, today: date, facts: UnitFacts) -> TenantItem:
    company_id = person.company_id
    row = session.execute(
        select(Unit.label, Lease.valid_from, Lease.valid_to, Lease.brixx_ref)
        .select_from(LeaseParty)
        .join(Lease, Lease.id == LeaseParty.lease_id)
        .join(Unit, Unit.id == Lease.unit_id)
        .where(
            LeaseParty.company_id == company_id,
            LeaseParty.person_id == person.id,
            (Lease.valid_to.is_(None)) | (Lease.valid_to >= today),
        )
        .order_by(Lease.valid_from.desc())
    ).first()
    identities = session.scalars(
        select(ChannelIdentity).where(
            ChannelIdentity.company_id == company_id,
            ChannelIdentity.person_id == person.id,
            ChannelIdentity.valid_to.is_(None),
        )
    ).all()
    label, start, end, lease_ref = row if row is not None else ("", None, None, None)
    rent_record = session.scalars(
        select(TenantRentPayment)
        .where(
            TenantRentPayment.company_id == company_id,
            TenantRentPayment.tenant_id == person.id,
        )
        .order_by(TenantRentPayment.billing_month.desc())
    ).first()
    monthly_rent = float(rent_record.contract_rent_cents) / 100.0 if rent_record else 0.0
    if not monthly_rent:
        monthly_rent = facts.for_lease(lease_ref)[0] or 0.0  # the contract's current rent lines in BRIXX
    status_str = (
        RENT_UNKNOWN if rent_record is None else ("overdue" if rent_record.status == "overdue" else "up_to_date")
    )
    overdue_days_val = rent_record.overdue_days if rent_record else 0

    return TenantItem(
        id=str(person.id),
        name=person.display_name,
        phone=next((i.identity for i in identities if i.channel == Channel.whatsapp), ""),
        email=next((i.identity for i in identities if i.channel == Channel.gmail), ""),
        unitLabel=label,
        leaseStart=f"{start:%d-%m-%Y}" if start else "",
        leaseEnd=f"{end:%d-%m-%Y}" if end else "",
        monthlyRentEur=monthly_rent,
        rentStatus=status_str,
        overdueDays=overdue_days_val,
    )


@router.get(
    "",
    response_model=TenantsResponse,
    summary="Get Active Tenant Directory",
    description="The company's tenants with contact details, unit and lease dates. Rent status is `unknown` for now.",
)
def get_tenants(
    engine: Annotated[Engine, Depends(get_engine)],
    principal: Annotated[Principal, Depends(require_session)],
    rent_status: str = Query(default="all", description="all, up_to_date, grace_period, overdue, unknown"),
) -> TenantsResponse:
    today = datetime.now(UTC).date()
    with Session(engine) as session:
        people = session.scalars(
            select(Person)
            .where(Person.company_id == principal.company_id, Person.kind == PersonKind.tenant)
            .order_by(Person.display_name.asc())
        ).all()
        facts = unit_facts(session, principal.company_id, today)
        items = [_item(session, p, today, facts) for p in people if p.display_name and "@" not in p.display_name]
    if not principal.access.can("tenants"):
        items = [_without_contact(t) for t in items]
    shown = items if rent_status == "all" else [t for t in items if t.rentStatus == rent_status]
    return TenantsResponse(
        totalTenants=len(items), overdueCount=sum(t.rentStatus == "overdue" for t in items), tenants=shown
    )


@router.get(
    "/{tenant_id}",
    response_model=TenantItem,
    summary="Get Specific Tenant Profile",
    description="One of the company's tenants with contact details, unit and lease dates.",
)
def get_tenant_details(
    tenant_id: str,
    engine: Annotated[Engine, Depends(get_engine)],
    principal: Annotated[Principal, Depends(require_session)],
) -> TenantItem:
    try:
        wanted = UUID(tenant_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="Tenant not found") from None
    with Session(engine) as session:
        person = session.scalars(
            select(Person).where(
                Person.id == wanted, Person.company_id == principal.company_id, Person.kind == PersonKind.tenant
            )
        ).first()
        if person is None:
            raise HTTPException(status_code=404, detail="Tenant not found")
        today = datetime.now(UTC).date()
        item = _item(session, person, today, unit_facts(session, principal.company_id, today))
    return item if principal.access.can("tenants") else _without_contact(item)
