"""Which Google Calendar organisers and addresses count as 'property-related': only the company's own, current ones."""

from datetime import date

import pytest
from sqlalchemy.orm import Session

from app.api.calendar.invites import _load_directory
from app.contracts import Channel
from app.db.enums import PersonKind
from app.db.models import ChannelIdentity, Company, Person, Unit

pytestmark = pytest.mark.integration
SINCE = date(2026, 1, 1)


def _person(db: Session, company: Company, name: str, email: str, *, channel: Channel = Channel.gmail) -> None:
    p = Person(company_id=company.id, kind=PersonKind.contractor, display_name=name, trade="plumber", valid_from=SINCE)
    db.add(p)
    db.flush()
    db.add(ChannelIdentity(company_id=company.id, person_id=p.id, channel=channel, identity=email, valid_from=SINCE))


def test_directory_has_own_current_emails_and_unit_addresses_only(db: Session, company: Company) -> None:
    other = Company(name="Other")
    db.add(other)
    db.flush()
    _person(db, company, "Kevin", "Kevin@ChahalBouw.nl")
    _person(db, company, "Phone only", "+31611111111", channel=Channel.whatsapp)
    _person(db, other, "Foreign", "foreign@other.nl")
    db.add_all(
        [
            Unit(company_id=company.id, label="A", address="Keizersgracht 42-A", valid_from=SINCE),
            Unit(company_id=company.id, label="No address", address=None, valid_from=SINCE),
            Unit(company_id=other.id, label="B", address="Elders 1", valid_from=SINCE),
        ]
    )
    db.flush()

    people, units = _load_directory(db, company.id)

    assert list(people) == ["kevin@chahalbouw.nl"]
    assert people["kevin@chahalbouw.nl"].name == "Kevin"
    assert [u.address for u in units] == ["Keizersgracht 42-A"]
