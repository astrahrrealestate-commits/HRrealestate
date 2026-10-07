"""Identity-first directory: an unknown phone/email becomes a person on first contact (no BRIXX in Phase 1)."""

from datetime import date

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.contracts import Channel
from app.db.enums import PersonKind
from app.db.models import ChannelIdentity, Company, Person
from app.directory.identity import resolve_person

pytestmark = pytest.mark.integration
TODAY = date(2026, 10, 7)
PHONE = "+31612345678"


def test_unknown_identity_creates_person_and_identity(db: Session, company: Company) -> None:
    person_id = resolve_person(db, company.id, Channel.whatsapp, PHONE, "Sanne de Vries", today=TODAY)
    person = db.get(Person, person_id)
    assert person is not None
    assert (person.kind, person.display_name, person.valid_from) == (PersonKind.other, "Sanne de Vries", TODAY)
    ident = db.scalar(select(ChannelIdentity).where(ChannelIdentity.person_id == person_id))
    assert ident is not None
    assert (ident.channel, ident.identity, ident.company_id) == (Channel.whatsapp, PHONE, company.id)


def test_known_identity_returns_same_person(db: Session, company: Company) -> None:
    first = resolve_person(db, company.id, Channel.whatsapp, PHONE, "Sanne", today=TODAY)
    again = resolve_person(db, company.id, Channel.whatsapp, PHONE, "Other name", today=TODAY)
    assert first == again
    assert db.scalar(select(func.count()).select_from(Person).where(Person.company_id == company.id)) == 1


def test_same_identity_in_other_company_is_a_different_person(db: Session, company: Company) -> None:
    other = Company(name="Andere BV")
    db.add(other)
    db.flush()
    assert resolve_person(db, company.id, Channel.gmail, "a@example.test", None, today=TODAY) != resolve_person(
        db, other.id, Channel.gmail, "a@example.test", None, today=TODAY
    )


def test_missing_display_name_falls_back_to_identity(db: Session, company: Company) -> None:
    person = db.get(Person, resolve_person(db, company.id, Channel.gmail, "x@example.test", "  ", today=TODAY))
    assert person is not None
    assert person.display_name == "x@example.test"


def test_expired_identity_is_not_reused(db: Session, company: Company) -> None:
    old = resolve_person(db, company.id, Channel.whatsapp, PHONE, "Old tenant", today=TODAY)
    ident = db.scalar(select(ChannelIdentity).where(ChannelIdentity.person_id == old))
    assert ident is not None
    ident.valid_to = TODAY
    db.flush()
    assert resolve_person(db, company.id, Channel.whatsapp, PHONE, "New tenant", today=TODAY) != old
