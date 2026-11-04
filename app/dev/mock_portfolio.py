"""Idempotent mock directory for the agent tour: units, tenants with leases, contractors, all reachable on WhatsApp.

Without it every sender is an unknown "other" and the finance agents (quote reader needs a *contractor*) never start.
"""

from datetime import date
from uuid import UUID

from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from app.contracts import Channel
from app.db.enums import PersonKind
from app.db.models import ChannelIdentity, Lease, LeaseParty, Person, Unit
from app.dev.mock_content import PEOPLE, UNITS, MockPerson

START = date(2025, 3, 1)


def seed_portfolio(engine: Engine, company_id: UUID) -> int:
    """Create what is missing. Returns how many people were added (0 on a second run)."""
    added = 0
    with Session(engine) as session, session.begin():
        units = {label: _unit(session, company_id, label, address) for label, address in UNITS.items()}
        for mock in PEOPLE:
            person, created = _person(session, company_id, mock)
            added += created
            if created and mock.unit:
                _lease(session, company_id, units[mock.unit], person)
    return added


def _unit(session: Session, company_id: UUID, label: str, address: str) -> UUID:
    found = session.scalar(select(Unit.id).where(Unit.company_id == company_id, Unit.label == label))
    if found:
        return found
    unit = Unit(company_id=company_id, label=label, address=address, valid_from=START)
    session.add(unit)
    session.flush()
    return unit.id


def _person(session: Session, company_id: UUID, mock: MockPerson) -> tuple[UUID, int]:
    owner = _owner_of(session, company_id, Channel.whatsapp, mock.phone)
    created = 0
    if owner is None:
        person = Person(
            company_id=company_id,
            kind=PersonKind(mock.kind),
            display_name=mock.name,
            trade=mock.trade,
            valid_from=START,
        )
        session.add(person)
        session.flush()
        owner, created = person.id, 1
        _identity(session, company_id, owner, Channel.whatsapp, mock.phone)
    if mock.email and _owner_of(session, company_id, Channel.gmail, mock.email) is None:
        _identity(session, company_id, owner, Channel.gmail, mock.email)
    return owner, created


def _owner_of(session: Session, company_id: UUID, channel: Channel, identity: str) -> UUID | None:
    return session.scalar(
        select(ChannelIdentity.person_id).where(
            ChannelIdentity.company_id == company_id,
            ChannelIdentity.channel == channel,
            ChannelIdentity.identity == identity,
            ChannelIdentity.valid_to.is_(None),
        )
    )


def _identity(session: Session, company_id: UUID, person_id: UUID, channel: Channel, identity: str) -> None:
    session.add(
        ChannelIdentity(
            company_id=company_id, person_id=person_id, channel=channel, identity=identity, valid_from=START
        )
    )


def _lease(session: Session, company_id: UUID, unit_id: UUID, person_id: UUID) -> None:
    lease = Lease(company_id=company_id, unit_id=unit_id, valid_from=START)
    session.add(lease)
    session.flush()
    session.add(LeaseParty(company_id=company_id, lease_id=lease.id, person_id=person_id, role="tenant"))
