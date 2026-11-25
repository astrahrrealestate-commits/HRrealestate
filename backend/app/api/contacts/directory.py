"""Contacts directory: list everyone the company talks to, add a contact by hand, rename or reclassify one.

People arrive from mail and WhatsApp as kind `other` (named after their email or number); the owner classifies them
here, or adds a contractor, tenant or maintenance person before they ever write.
"""

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import Engine, distinct, func, select
from sqlalchemy.orm import Session

from app.api.deps import get_engine
from app.api.v1.access import require_section
from app.api.v1.auth import Principal, require_session
from app.contracts import CaseState, Channel
from app.core.errors import NotFoundError
from app.db.enums import PersonKind
from app.db.models import Case, ChannelIdentity, Lease, LeaseParty, Person, Unit
from app.db.models.finance import TenantRentPayment
from app.directory.brixx.unit_facts import UnitFacts, unit_facts
from app.directory.contacts import (
    CATEGORIES,
    ContactConflictError,
    InvalidContactError,
    category_of,
    create_contact,
    update_contact,
)

router = APIRouter(prefix="/api/contacts", tags=["contacts"], dependencies=[Depends(require_section("contacts"))])
_ROLE_LABEL = {
    "tenant": "Tenant",
    "owner": "Owner",
    "legal": "Legal",
    "vve": "VvE",
    "business": "Business",
    "utility": "Utility",
    "municipal": "Municipality",
}


class ContactOut(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: str
    name: str
    category: str
    trade_or_role: str = Field(alias="tradeOrRole")
    unit_role: str = Field(alias="unitRole")
    email: str
    phone: str
    secondary_emails: list[str] = Field(default_factory=list, alias="secondaryEmails")
    secondary_phones: list[str] = Field(default_factory=list, alias="secondaryPhones")
    property_address: str = Field(alias="propertyAddress")
    residential_address: str = Field(alias="residentialAddress")
    agreement_period: str = Field(alias="agreementPeriod")
    status: str = "active"
    rent_status: str = Field(default="unknown", alias="rentStatus", description="up_to_date | overdue | unknown")
    monthly_rent_eur: float | None = Field(default=None, alias="monthlyRentEur")
    deposit_eur: float | None = Field(default=None, alias="depositEur")
    lease_start: str | None = Field(default=None, alias="leaseStart")
    lease_end: str | None = Field(default=None, alias="leaseEnd", description="None for an open-ended lease")
    open_tickets_count: int = Field(default=0, alias="openTicketsCount")
    notes: str = ""
    trade: str = Field(default="", description="The stored trade or role, empty when none")
    source: str = Field(description="brixx | directory (added by hand or created from a message)")
    unclassified: bool = Field(description="created from a message and not yet given a category")
    documents: list[Any] = []
    emails: list[Any] = []
    whatsapp_messages: list[Any] = Field(default=[], alias="whatsappMessages")
    leases: list[Any] = []


class ContactIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    category: str = Field(
        description="tenant | contractor | owner | legal | vve | business | utility | municipal | other"
    )
    trade: str | None = Field(default=None, max_length=100, description="Trade or role, e.g. Plumber or Caretaker")
    email: str | None = Field(default=None, max_length=320)
    phone: str | None = Field(default=None, max_length=40)


class ContactPatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    category: str | None = None
    trade: str | None = Field(default=None, max_length=100)
    email: str | None = Field(default=None, max_length=320)
    phone: str | None = Field(default=None, max_length=40)


@dataclass(frozen=True)
class _Tenancy:
    unit: str = ""
    address: str = ""
    period: str = ""
    lease_ref: str | None = None
    start: date | None = None
    end: date | None = None


def _tenancies(session: Session, company_id: UUID, person_ids: list[UUID]) -> dict[UUID, _Tenancy]:
    """Each person's most recent lease (as tenant or co-tenant), from the directory."""
    if not person_ids:
        return {}
    rows = session.execute(
        select(LeaseParty.person_id, Unit.label, Unit.address, Lease.valid_from, Lease.valid_to, Lease.brixx_ref)
        .select_from(LeaseParty)
        .join(Lease, Lease.id == LeaseParty.lease_id)
        .join(Unit, Unit.id == Lease.unit_id)
        .where(LeaseParty.company_id == company_id, LeaseParty.person_id.in_(person_ids))
        .order_by(Lease.valid_to.is_(None).desc(), Lease.valid_to.desc(), Lease.valid_from.desc())
    ).all()
    found: dict[UUID, _Tenancy] = {}
    for person_id, label, address, start, end, ref in rows:
        if person_id in found:
            continue
        period = f"{start:%d %b %Y} — {end:%d %b %Y}" if end else f"Since {start:%d %b %Y} (open-ended)"
        found[person_id] = _Tenancy(label, address or label, period, ref, start, end)
    return found


def _tenancy(session: Session, company_id: UUID, person_id: UUID) -> _Tenancy:
    return _tenancies(session, company_id, [person_id]).get(person_id, _Tenancy())


def _role_label(category: str, trade: str | None) -> str:
    if category == "contractor":
        return f"{trade.capitalize()} Contractor" if trade else "Maintenance Contractor"
    if category == "other":
        return trade.capitalize() if trade else "Contact"
    return _ROLE_LABEL[category]


@dataclass
class _Identities:
    primary_email: str = ""
    primary_phone: str = ""
    secondary_emails: list[str] = field(default_factory=list)
    secondary_phones: list[str] = field(default_factory=list)


def _identities(session: Session, company_id: UUID, person_ids: list[UUID]) -> dict[UUID, _Identities]:
    rows = session.execute(
        select(ChannelIdentity.person_id, ChannelIdentity.channel, ChannelIdentity.identity)
        .where(
            ChannelIdentity.company_id == company_id,
            ChannelIdentity.person_id.in_(person_ids),
            ChannelIdentity.valid_to.is_(None),
        )
        .order_by(ChannelIdentity.valid_from.asc().nulls_last(), ChannelIdentity.id.asc())
    ).all()
    found: dict[UUID, _Identities] = defaultdict(_Identities)
    for person_id, channel, identity in rows:
        p = found[person_id]
        if channel == Channel.gmail:
            if not p.primary_email:
                p.primary_email = identity
            elif identity != p.primary_email and identity not in p.secondary_emails:
                p.secondary_emails.append(identity)
        elif channel == Channel.whatsapp:
            if not p.primary_phone:
                p.primary_phone = identity
            elif identity != p.primary_phone and identity not in p.secondary_phones:
                p.secondary_phones.append(identity)
    return found


def _open_cases(session: Session, company_id: UUID, person_ids: list[UUID]) -> dict[UUID, int]:
    rows = session.execute(
        select(Case.primary_person_id, func.count(Case.id))
        .where(Case.company_id == company_id, Case.primary_person_id.in_(person_ids), Case.state != CaseState.resolved)
        .group_by(Case.primary_person_id)
    ).all()
    return {person_id: count for person_id, count in rows if person_id is not None}


def _rent_known(session: Session, company_id: UUID, person_ids: list[UUID]) -> set[UUID]:
    """Tenants with any rent record: only for them can rent be called up to date."""
    rows = session.scalars(
        select(distinct(TenantRentPayment.tenant_id)).where(
            TenantRentPayment.company_id == company_id, TenantRentPayment.tenant_id.in_(person_ids)
        )
    ).all()
    return set(rows)


def _overdue_tenants(session: Session, company_id: UUID, person_ids: list[UUID]) -> set[UUID]:
    rows = session.scalars(
        select(distinct(TenantRentPayment.tenant_id)).where(
            TenantRentPayment.company_id == company_id,
            TenantRentPayment.tenant_id.in_(person_ids),
            TenantRentPayment.status == "overdue",
        )
    ).all()
    return set(rows)


def _contact(
    person: Person,
    idents: _Identities,
    tenancy: _Tenancy,
    open_cases: int,
    facts: UnitFacts,
    is_overdue: bool = False,
    rent_known: bool = False,
) -> ContactOut:
    category = category_of(person.kind, person.trade)
    rent, deposit = facts.for_lease(tenancy.lease_ref)
    role = _role_label(category, person.trade)
    today = datetime.now(UTC).date()
    status_val = "active"
    if category == "tenant" and tenancy.end:
        if tenancy.end < today:
            status_val = "ended"
        elif (tenancy.end - today).days <= 90:
            status_val = "ending_soon"

    return ContactOut(
        id=str(person.id),
        name=person.display_name.strip(),
        category=category,
        trade_or_role=role,
        unit_role=tenancy.unit if category == "tenant" else (person.trade.capitalize() if person.trade else role),
        email=idents.primary_email,
        phone=idents.primary_phone,
        secondary_emails=idents.secondary_emails,
        secondary_phones=idents.secondary_phones,
        property_address=tenancy.address,
        residential_address=tenancy.address,
        agreement_period=tenancy.period,
        status=status_val,
        rent_status="overdue" if is_overdue else ("up_to_date" if rent_known else "unknown"),
        monthly_rent_eur=rent,
        deposit_eur=deposit,
        lease_start=f"{tenancy.start:%d-%m-%Y}" if tenancy.start else None,
        lease_end=f"{tenancy.end:%d-%m-%Y}" if tenancy.end else None,
        open_tickets_count=open_cases,
        trade=person.trade or "",
        source="brixx" if person.brixx_ref else "directory",
        unclassified=person.kind is PersonKind.other and not person.trade and not person.brixx_ref,
    )


def _one(session: Session, person: Person) -> ContactOut:
    ids = [person.id]
    overdue_set = _overdue_tenants(session, person.company_id, ids)
    idents = _identities(session, person.company_id, ids).get(person.id, _Identities())
    is_tenant = category_of(person.kind, person.trade) == "tenant"
    tenancy = _tenancy(session, person.company_id, person.id) if is_tenant else _Tenancy()
    return _contact(
        person,
        idents,
        tenancy,
        _open_cases(session, person.company_id, ids).get(person.id, 0),
        unit_facts(session, person.company_id, datetime.now(UTC).date()),
        is_overdue=person.id in overdue_set,
        rent_known=person.id in _rent_known(session, person.company_id, ids),
    )


@router.get(
    "",
    response_model=list[ContactOut],
    summary="List Contacts from Database",
    description="The company's directory: tenants, contractors and everyone mail or WhatsApp created, by name.",
)
def list_contacts(
    engine: Annotated[Engine, Depends(get_engine)],
    principal: Annotated[Principal, Depends(require_session)],
    audience: str = Query(default="all", description="all | tenant | contractor"),
) -> list[ContactOut]:
    """The signed-in company's directory contacts, with facts from their lease and cases (never made up). People
    created from a message are listed under their email or number until the owner names them."""
    company_id = principal.company_id
    stmt = select(Person).where(Person.company_id == company_id).order_by(func.lower(Person.display_name), Person.id)
    if audience in ("tenant", "contractor"):
        stmt = stmt.where(Person.kind == PersonKind(audience))
    with Session(engine) as session:
        people = [p for p in session.scalars(stmt) if p.display_name.strip()]
        ids = [p.id for p in people]
        tenant_ids = [p.id for p in people if category_of(p.kind, p.trade) == "tenant"]
        identities = _identities(session, company_id, ids)
        tenancies = _tenancies(session, company_id, tenant_ids)
        cases = _open_cases(session, company_id, ids)
        overdue_set = _overdue_tenants(session, company_id, ids)
        known = _rent_known(session, company_id, ids)
        facts = unit_facts(session, company_id, datetime.now(UTC).date())
        seen: set[tuple[str, PersonKind]] = set()
        results: list[ContactOut] = []
        for person in people:
            key = (person.display_name.strip().lower(), person.kind)
            if person.brixx_ref and key in seen:  # BRIXX can list one relation twice; two real contacts stay two
                continue
            if person.brixx_ref:
                seen.add(key)
            results.append(
                _contact(
                    person,
                    identities.get(person.id, _Identities()),
                    tenancies.get(person.id, _Tenancy()),
                    cases.get(person.id, 0),
                    facts,
                    is_overdue=person.id in overdue_set,
                    rent_known=person.id in known,
                )
            )
        return results


def _bad_category(category: str | None) -> None:
    if category is not None and category not in CATEGORIES:
        raise HTTPException(status_code=422, detail=f"category must be one of: {', '.join(CATEGORIES)}")


def _http(exc: ContactConflictError | InvalidContactError | NotFoundError) -> HTTPException:
    if isinstance(exc, ContactConflictError):
        return HTTPException(status_code=409, detail=str(exc))
    if isinstance(exc, NotFoundError):
        return HTTPException(status_code=404, detail="contact not found")
    return HTTPException(status_code=422, detail=str(exc))


@router.post("", response_model=ContactOut, status_code=201, summary="Add a Contact")
def add_contact(
    body: ContactIn,
    engine: Annotated[Engine, Depends(get_engine)],
    principal: Annotated[Principal, Depends(require_session)],
) -> ContactOut:
    """Adds a contact by hand. An email or number that mail/WhatsApp already created as an unclassified person is
    classified in place; one that belongs to a classified contact answers 409."""
    _bad_category(body.category)
    try:
        with Session(engine) as session, session.begin():
            person = create_contact(
                session,
                principal.company_id,
                name=body.name,
                category=body.category,
                trade=body.trade,
                email=body.email,
                phone=body.phone,
                today=datetime.now(UTC).date(),
            )
            return _one(session, person)
    except (ContactConflictError, InvalidContactError, NotFoundError) as exc:
        raise _http(exc) from None


@router.patch("/{contact_id}", response_model=ContactOut, summary="Rename or Reclassify a Contact")
def edit_contact(
    contact_id: UUID,
    body: ContactPatch,
    engine: Annotated[Engine, Depends(get_engine)],
    principal: Annotated[Principal, Depends(require_session)],
) -> ContactOut:
    _bad_category(body.category)
    try:
        with Session(engine) as session, session.begin():
            person = update_contact(
                session,
                principal.company_id,
                contact_id,
                name=body.name,
                category=body.category,
                trade=body.trade,
                email=body.email,
                phone=body.phone,
                today=datetime.now(UTC).date(),
            )
            return _one(session, person)
    except (ContactConflictError, InvalidContactError, NotFoundError) as exc:
        raise _http(exc) from None
