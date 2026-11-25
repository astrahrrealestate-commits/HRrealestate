"""Properties REST API Routes.

Feeds the portfolio directory (units, occupancy, tenant and lease end) to the Next.js frontend from the company's own
directory tables. Rent amounts and lockbox codes are not stored there yet, so they are not reported: the rent is 0.0
(unknown, see `rentDataAvailable` on the dashboard pulse) and no lockbox code is ever returned.
"""

from collections import defaultdict
from dataclasses import dataclass
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
from app.directory.brixx.unit_facts import UnitFacts, unit_facts

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


@dataclass(frozen=True)
class _UnitBatch:
    leases_by_unit: dict[UUID, Lease]
    tenants_by_lease: dict[UUID, Person]
    identities_by_person: dict[UUID, tuple[str | None, str | None]]
    rent_by_unit: dict[UUID, TenantRentPayment]
    open_tickets_by_unit: dict[UUID, int]


def _load_units_batch(session: Session, company_id: UUID, unit_ids: list[UUID], today: date) -> _UnitBatch:
    if not unit_ids:
        return _UnitBatch({}, {}, {}, {}, {})

    leases_by_unit: dict[UUID, Lease] = {}
    for lease in session.scalars(
        select(Lease)
        .where(
            Lease.company_id == company_id,
            Lease.unit_id.in_(unit_ids),
            (Lease.valid_to.is_(None)) | (Lease.valid_to >= today),
            Lease.valid_from <= today,
        )
        .order_by(Lease.valid_from.desc())
    ).all():
        if lease.unit_id not in leases_by_unit:
            leases_by_unit[lease.unit_id] = lease

    lease_ids = [lease.id for lease in leases_by_unit.values()]
    tenants_by_lease: dict[UUID, Person] = {}
    if lease_ids:
        for lid, person in session.execute(
            select(LeaseParty.lease_id, Person)
            .join(Person, Person.id == LeaseParty.person_id)
            .where(
                LeaseParty.company_id == company_id,
                LeaseParty.lease_id.in_(lease_ids),
                LeaseParty.role == "tenant",
            )
        ).all():
            if lid not in tenants_by_lease:
                tenants_by_lease[lid] = person

    person_ids = [p.id for p in tenants_by_lease.values()]
    ident_map: dict[UUID, dict[str, str]] = defaultdict(dict)
    if person_ids:
        for pid, ch, ident in session.execute(
            select(ChannelIdentity.person_id, ChannelIdentity.channel, ChannelIdentity.identity).where(
                ChannelIdentity.company_id == company_id,
                ChannelIdentity.person_id.in_(person_ids),
                ChannelIdentity.valid_to.is_(None),
            )
        ).all():
            entry = ident_map[pid]
            if ch == Channel.whatsapp and "phone" not in entry:
                entry["phone"] = ident
            elif ch == Channel.gmail and "email" not in entry:
                entry["email"] = ident
    identities_by_person = {pid: (d.get("phone"), d.get("email")) for pid, d in ident_map.items()}

    rent_by_unit: dict[UUID, TenantRentPayment] = {}
    for rent in session.scalars(
        select(TenantRentPayment)
        .where(TenantRentPayment.company_id == company_id, TenantRentPayment.unit_id.in_(unit_ids))
        .order_by(TenantRentPayment.billing_month.desc())
    ).all():
        if rent.unit_id not in rent_by_unit:
            rent_by_unit[rent.unit_id] = rent

    open_tickets_by_unit: dict[UUID, int] = {
        uid: int(cnt)
        for uid, cnt in session.execute(
            select(Case.unit_id, func.count(Case.id))
            .where(Case.company_id == company_id, Case.unit_id.in_(unit_ids), Case.state != CaseState.resolved)
            .group_by(Case.unit_id)
        ).all()
        if uid is not None
    }
    return _UnitBatch(
        leases_by_unit=leases_by_unit,
        tenants_by_lease=tenants_by_lease,
        identities_by_person=identities_by_person,
        rent_by_unit=rent_by_unit,
        open_tickets_by_unit=open_tickets_by_unit,
    )


def _item_from_batch(unit: Unit, today: date, facts: UnitFacts, batch: _UnitBatch) -> UnitItem:
    lease = batch.leases_by_unit.get(unit.id)
    tenant = batch.tenants_by_lease.get(lease.id) if lease is not None else None
    tenant_phone, tenant_email = (
        batch.identities_by_person.get(tenant.id, (None, None)) if tenant is not None else (None, None)
    )
    monthly_rent = 0.0
    rent_status = None
    if lease is not None and tenant is not None:
        rent_record = batch.rent_by_unit.get(unit.id)
        if rent_record:
            monthly_rent = float(rent_record.contract_rent_cents) / 100.0
            rent_status = "overdue" if rent_record.status == "overdue" else "up_to_date"

    open_tickets = batch.open_tickets_by_unit.get(unit.id, 0)
    brixx_rent, deposit = facts.for_lease(lease.brixx_ref if lease is not None else None)
    if lease is not None and not monthly_rent and brixx_rent:
        monthly_rent = brixx_rent  # the contract's current rent lines in BRIXX when no rent roll is recorded here
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
        floor=None,
        livingAreaSqm=facts.area_sqm.get(unit.brixx_ref) if unit.brixx_ref else None,
        depositEur=deposit,
        rentStatus=rent_status,
        activeTicketCount=open_tickets,
    )


def _item(session: Session, unit: Unit, today: date, facts: UnitFacts) -> UnitItem:
    """The unit with its current lease: one that has not ended (open-ended, or ending today or later)."""
    batch = _load_units_batch(session, unit.company_id, [unit.id], today)
    return _item_from_batch(unit, today, facts, batch)


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
        units = list(
            session.scalars(
                select(Unit)
                .where(Unit.company_id == principal.company_id, Unit.valid_to.is_(None))
                .order_by(Unit.label.asc())
            ).all()
        )
        facts = unit_facts(session, principal.company_id, today)
        batch = _load_units_batch(session, principal.company_id, [u.id for u in units], today)
        items = [_for_viewer(_item_from_batch(unit, today, facts, batch), principal) for unit in units]
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
        today = datetime.now(UTC).date()
        return _for_viewer(_item(session, unit, today, unit_facts(session, principal.company_id, today)), principal)
