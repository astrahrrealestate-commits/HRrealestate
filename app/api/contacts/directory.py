"""Contacts directory: list everyone the company talks to, add a contact by hand, rename or reclassify one.

People arrive from mail and WhatsApp as kind `other` (named after their email or number); the owner classifies them
here, or adds a contractor, tenant or maintenance person before they ever write.
"""

from collections import defaultdict
from datetime import UTC, datetime
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import Engine, func, select
from sqlalchemy.orm import Session

from app.api.deps import get_engine
from app.api.v1.access import require_section
from app.api.v1.auth import Principal, require_session
from app.contracts import CaseState, Channel
from app.core.errors import NotFoundError
from app.db.enums import PersonKind
from app.db.models import Case, ChannelIdentity, Lease, LeaseParty, Person, Unit
from app.directory.contacts import (
    CATEGORIES,
    ContactConflictError,
    InvalidContactError,
    category_of,
    create_contact,
    update_contact,
)

router = APIRouter(prefix="/api/contacts", tags=["contacts"], dependencies=[Depends(require_section("contacts"))])
_ROLE_LABEL = {"tenant": "Tenant", "owner": "Owner", "utility": "Utility", "municipal": "Municipality"}


class ContactOut(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: str
    name: str
    category: str
    trade_or_role: str = Field(alias="tradeOrRole")
    unit_role: str = Field(alias="unitRole")
    email: str
    phone: str
    property_address: str = Field(alias="propertyAddress")
    residential_address: str = Field(alias="residentialAddress")
    agreement_period: str = Field(alias="agreementPeriod")
    status: str = "active"
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
    category: str = Field(description="tenant | contractor | owner | utility | municipal | other")
    trade: str | None = Field(default=None, max_length=100, description="Trade or role, e.g. Plumber or Caretaker")
    email: str | None = Field(default=None, max_length=320)
    phone: str | None = Field(default=None, max_length=40)


class ContactPatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    category: str | None = None
    trade: str | None = Field(default=None, max_length=100)


def _tenancy(session: Session, company_id: UUID, person_id: UUID) -> tuple[str, str, str]:
    """(unit label, unit address, agreement period) of the person's most recent lease, from the directory. Blank when
    the person has no lease on file: nothing is invented."""
    row = session.execute(
        select(Unit.label, Unit.address, Lease.valid_from, Lease.valid_to)
        .select_from(LeaseParty)
        .join(Lease, Lease.id == LeaseParty.lease_id)
        .join(Unit, Unit.id == Lease.unit_id)
        .where(LeaseParty.company_id == company_id, LeaseParty.person_id == person_id)
        .order_by(Lease.valid_from.desc())
    ).first()
    if row is None:
        return "", "", ""
    label, address, start, end = row
    period = f"{start:%d %b %Y} — {end:%d %b %Y}" if end else f"Since {start:%d %b %Y} (open-ended)"
    return label, address or label, period


def _role_label(category: str, trade: str | None) -> str:
    if category == "contractor":
        return f"{trade.capitalize()} Contractor" if trade else "Maintenance Contractor"
    if category == "other":
        return trade.capitalize() if trade else "Contact"
    return _ROLE_LABEL[category]


def _identities(session: Session, company_id: UUID, person_ids: list[UUID]) -> dict[UUID, dict[Channel, str]]:
    rows = session.execute(
        select(ChannelIdentity.person_id, ChannelIdentity.channel, ChannelIdentity.identity).where(
            ChannelIdentity.company_id == company_id,
            ChannelIdentity.person_id.in_(person_ids),
            ChannelIdentity.valid_to.is_(None),
        )
    ).all()
    found: dict[UUID, dict[Channel, str]] = defaultdict(dict)
    for person_id, channel, identity in rows:
        found[person_id].setdefault(channel, identity)
    return found


def _open_cases(session: Session, company_id: UUID, person_ids: list[UUID]) -> dict[UUID, int]:
    rows = session.execute(
        select(Case.primary_person_id, func.count(Case.id))
        .where(Case.company_id == company_id, Case.primary_person_id.in_(person_ids), Case.state != CaseState.resolved)
        .group_by(Case.primary_person_id)
    ).all()
    return {person_id: count for person_id, count in rows if person_id is not None}


def _contact(session: Session, person: Person, identities: dict[Channel, str], open_cases: int) -> ContactOut:
    category = category_of(person.kind, person.trade)
    unit, address, period = _tenancy(session, person.company_id, person.id) if category == "tenant" else ("", "", "")
    role = _role_label(category, person.trade)
    return ContactOut(
        id=str(person.id),
        name=person.display_name.strip(),
        category=category,
        trade_or_role=role,
        unit_role=unit if category == "tenant" else (person.trade.capitalize() if person.trade else role),
        email=identities.get(Channel.gmail, ""),
        phone=identities.get(Channel.whatsapp, ""),
        property_address=address,
        residential_address=address,
        agreement_period=period,
        open_tickets_count=open_cases,
        trade=person.trade or "",
        source="brixx" if person.brixx_ref else "directory",
        unclassified=person.kind is PersonKind.other and not person.trade and not person.brixx_ref,
    )


def _one(session: Session, person: Person) -> ContactOut:
    ids = [person.id]
    return _contact(
        session,
        person,
        _identities(session, person.company_id, ids).get(person.id, {}),
        _open_cases(session, person.company_id, ids).get(person.id, 0),
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
        identities, cases = _identities(session, company_id, ids), _open_cases(session, company_id, ids)
        seen: set[tuple[str, PersonKind]] = set()
        results: list[ContactOut] = []
        for person in people:
            key = (person.display_name.strip().lower(), person.kind)
            if person.brixx_ref and key in seen:  # BRIXX can list one relation twice; two real contacts stay two
                continue
            if person.brixx_ref:
                seen.add(key)
            results.append(_contact(session, person, identities.get(person.id, {}), cases.get(person.id, 0)))
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
                session, principal.company_id, contact_id, name=body.name, category=body.category, trade=body.trade
            )
            return _one(session, person)
    except (ContactConflictError, InvalidContactError, NotFoundError) as exc:
        raise _http(exc) from None
