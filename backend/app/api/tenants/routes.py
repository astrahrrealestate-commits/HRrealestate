"""Tenants REST API Routes.

Feeds the tenant directory (contact details, unit, lease dates) to the Next.js frontend from the company's own
directory tables. Rent amounts and payment status are not stored there yet, so the rent is 0.0 and the status is
`unknown` rather than a guess; arrears arrive with the BRIXX rent mirror.
"""

from collections import defaultdict
from dataclasses import dataclass
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
    secondary_phones: list[str] = Field(default_factory=list, alias="secondaryPhones")
    secondary_emails: list[str] = Field(default_factory=list, alias="secondaryEmails")
    unitLabel: str
    leaseStart: str
    leaseEnd: str
    status: str = Field(default="active", description="active | ending_soon | ended")
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


@dataclass(frozen=True)
class _TenantsBatch:
    lease_by_person: dict[UUID, tuple[str, date, date | None, str | None]]
    identities_by_person: dict[UUID, list[tuple[Channel, str]]]
    rent_by_person: dict[UUID, TenantRentPayment]


def _load_tenants_batch(session: Session, company_id: UUID, person_ids: list[UUID]) -> _TenantsBatch:
    if not person_ids:
        return _TenantsBatch({}, {}, {})

    lease_by_person: dict[UUID, tuple[str, date, date | None, str | None]] = {}
    for pid, label, start, end, ref in session.execute(
        select(LeaseParty.person_id, Unit.label, Lease.valid_from, Lease.valid_to, Lease.brixx_ref)
        .select_from(LeaseParty)
        .join(Lease, Lease.id == LeaseParty.lease_id)
        .join(Unit, Unit.id == Lease.unit_id)
        .where(
            LeaseParty.company_id == company_id,
            LeaseParty.person_id.in_(person_ids),
        )
        .order_by(Lease.valid_to.is_(None).desc(), Lease.valid_to.desc(), Lease.valid_from.desc())
    ).all():
        if pid not in lease_by_person:
            lease_by_person[pid] = (label, start, end, ref)

    identities_by_person: dict[UUID, list[tuple[Channel, str]]] = defaultdict(list)
    for pid, ch, ident in session.execute(
        select(ChannelIdentity.person_id, ChannelIdentity.channel, ChannelIdentity.identity)
        .where(
            ChannelIdentity.company_id == company_id,
            ChannelIdentity.person_id.in_(person_ids),
            ChannelIdentity.valid_to.is_(None),
        )
        .order_by(ChannelIdentity.valid_from.asc().nulls_last(), ChannelIdentity.id.asc())
    ).all():
        identities_by_person[pid].append((ch, ident))

    rent_by_person: dict[UUID, TenantRentPayment] = {}
    for rent in session.scalars(
        select(TenantRentPayment)
        .where(TenantRentPayment.company_id == company_id, TenantRentPayment.tenant_id.in_(person_ids))
        .order_by(TenantRentPayment.billing_month.desc())
    ).all():
        if rent.tenant_id not in rent_by_person:
            rent_by_person[rent.tenant_id] = rent

    return _TenantsBatch(
        lease_by_person=lease_by_person,
        identities_by_person=identities_by_person,
        rent_by_person=rent_by_person,
    )


def _item_from_batch(person: Person, today: date, facts: UnitFacts, batch: _TenantsBatch) -> TenantItem:
    row = batch.lease_by_person.get(person.id)
    identities = batch.identities_by_person.get(person.id, ())
    label, start, end, lease_ref = row if row is not None else ("", None, None, None)
    rent_record = batch.rent_by_person.get(person.id)
    monthly_rent = float(rent_record.contract_rent_cents) / 100.0 if rent_record else 0.0
    if not monthly_rent:
        monthly_rent = facts.for_lease(lease_ref)[0] or 0.0  # the contract's current rent lines in BRIXX
    status_str = (
        RENT_UNKNOWN if rent_record is None else ("overdue" if rent_record.status == "overdue" else "up_to_date")
    )
    overdue_days_val = rent_record.overdue_days if rent_record else 0

    emails = [ident for ch, ident in identities if ch == Channel.gmail]
    phones = [ident for ch, ident in identities if ch == Channel.whatsapp]
    primary_email = emails[0] if emails else ""
    secondary_emails = [e for e in emails[1:] if e != primary_email]
    primary_phone = phones[0] if phones else ""
    secondary_phones = [p for p in phones[1:] if p != primary_phone]

    lease_status_val = "active"
    if end:
        if end < today:
            lease_status_val = "ended"
        elif (end - today).days <= 90:
            lease_status_val = "ending_soon"

    return TenantItem(
        id=str(person.id),
        name=person.display_name,
        phone=primary_phone,
        email=primary_email,
        secondaryPhones=secondary_phones,
        secondaryEmails=secondary_emails,
        unitLabel=label,
        leaseStart=f"{start:%d-%m-%Y}" if start else "",
        leaseEnd=f"{end:%d-%m-%Y}" if end else "",
        status=lease_status_val,
        monthlyRentEur=monthly_rent,
        rentStatus=status_str,
        overdueDays=overdue_days_val,
    )


def _item(session: Session, person: Person, today: date, facts: UnitFacts) -> TenantItem:
    batch = _load_tenants_batch(session, person.company_id, [person.id])
    return _item_from_batch(person, today, facts, batch)


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
    lease_status: str = Query(default="all", description="all, active, ending_soon, ended"),
) -> TenantsResponse:
    today = datetime.now(UTC).date()
    with Session(engine) as session:
        people = [
            p
            for p in session.scalars(
                select(Person)
                .where(Person.company_id == principal.company_id, Person.kind == PersonKind.tenant)
                .order_by(Person.display_name.asc())
            ).all()
            if p.display_name and "@" not in p.display_name
        ]
        facts = unit_facts(session, principal.company_id, today)
        batch = _load_tenants_batch(session, principal.company_id, [p.id for p in people])
        items = [_item_from_batch(p, today, facts, batch) for p in people]
    if not principal.access.can("tenants"):
        items = [_without_contact(t) for t in items]
    shown = items
    if rent_status != "all":
        shown = [t for t in shown if t.rentStatus == rent_status]
    if lease_status != "all":
        if lease_status == "active":
            shown = [t for t in shown if t.status in ("active", "ending_soon")]
        else:
            shown = [t for t in shown if t.status == lease_status]
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
