"""Adding and classifying contacts against real Postgres: hand-added people, people created from mail/WhatsApp, and
the company wall around both."""

from collections.abc import Iterator
from dataclasses import dataclass
from datetime import date
from typing import Any
from uuid import UUID, uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from app.api.v1.auth import Principal
from app.contracts import Channel
from app.core.settings import Settings
from app.db.enums import PersonKind
from app.db.models import ChannelIdentity, Company, Person
from app.directory.identity import resolve_person
from tests.integration.access_support import CSRF, add_person_to_team, build_app, signed_in
from tests.integration.conftest import purge_company

pytestmark = pytest.mark.integration
SINCE = date(2026, 1, 1)
CONTACTS = "/api/contacts"


@dataclass
class Book:
    app: FastAPI
    settings: Settings
    engine: Engine
    company: UUID
    other_company: UUID
    owner: Principal


@pytest.fixture
def book(migrated_engine: Engine, pg_url: str, committed_company: Company) -> Iterator[Book]:
    with Session(migrated_engine, expire_on_commit=False) as s:
        other = Company(name="Other BV")
        s.add(other)
        s.commit()
    owner = add_person_to_team(migrated_engine, committed_company.id, f"o-{uuid4().hex[:6]}@t.test", role="superadmin")
    app, settings = build_app(migrated_engine, pg_url)
    yield Book(app, settings, migrated_engine, committed_company.id, other.id, owner)
    purge_company(migrated_engine, other.id)


@pytest.fixture
def client(book: Book) -> Iterator[TestClient]:
    with signed_in(book.app, book.settings, book.owner) as c:
        yield c


def _add(client: TestClient, **body: Any) -> Any:
    payload = {"name": "Jan Jansen", "category": "contractor"} | body
    return client.post(CONTACTS, json=payload, headers=CSRF)


def _message_person(book: Book, channel: Channel, identity: str, company: UUID | None = None) -> UUID:
    """The person mail/WhatsApp creates the first time an unknown sender writes."""
    with Session(book.engine) as s, s.begin():
        return resolve_person(s, company or book.company, channel, identity, None, today=SINCE)


def test_a_hand_added_contractor_is_listed_with_normalised_email_and_phone(client: TestClient) -> None:
    response = _add(client, name="Jan Loodgieter", trade="plumber", email="Jan@Plumb.TEST", phone="06 12345678")
    assert response.status_code == 201
    created = response.json()
    assert (created["category"], created["email"], created["phone"]) == ("contractor", "jan@plumb.test", "+31612345678")
    assert created["tradeOrRole"] == "Plumber Contractor"
    assert (created["unclassified"], created["source"]) == (False, "directory")
    listed = client.get(CONTACTS).json()
    assert [(c["id"], c["name"]) for c in listed] == [(created["id"], "Jan Loodgieter")]


def test_a_maintenance_person_without_a_trade_and_the_other_categories(client: TestClient) -> None:
    categories = {
        "Caretaker": ("contractor", None, "contractor", "Maintenance Contractor"),
        "Eneco": ("utility", None, "utility", "Utility"),
        "Gemeente": ("municipal", None, "municipal", "Municipality"),
        "Notary": ("other", "notary", "other", "Notary"),
        "Anna": ("tenant", None, "tenant", "Tenant"),
        "Harjot": ("owner", None, "owner", "Owner"),
    }
    for name, (category, trade, _, _) in categories.items():
        assert _add(client, name=name, category=category, trade=trade).status_code == 201
    by_name = {c["name"]: c for c in client.get(CONTACTS).json()}
    for name, (_, _, shown_category, label) in categories.items():
        assert (by_name[name]["category"], by_name[name]["tradeOrRole"]) == (shown_category, label), name


def test_people_created_from_mail_and_whatsapp_are_listed_under_their_address_until_named(
    book: Book, client: TestClient
) -> None:
    _message_person(book, Channel.gmail, "pieter@bouw.test")
    _message_person(book, Channel.whatsapp, "+31611111111")
    listed = {c["name"]: c for c in client.get(CONTACTS).json()}
    assert set(listed) == {"pieter@bouw.test", "+31611111111"}
    assert listed["pieter@bouw.test"]["email"] == "pieter@bouw.test"
    assert listed["+31611111111"]["phone"] == "+31611111111"
    assert all(c["unclassified"] and c["category"] == "other" for c in listed.values())


def test_adding_a_contact_for_a_known_sender_classifies_that_person_instead_of_duplicating(
    book: Book, client: TestClient
) -> None:
    person_id = _message_person(book, Channel.gmail, "pieter@bouw.test")
    response = _add(client, name="Pieter Bakker", trade="roofer", email="PIETER@bouw.test", phone="0611111111")
    assert response.status_code == 201
    assert response.json()["id"] == str(person_id)
    listed = client.get(CONTACTS).json()
    assert [(c["name"], c["category"], c["phone"], c["unclassified"]) for c in listed] == [
        ("Pieter Bakker", "contractor", "+31611111111", False)
    ]
    with Session(book.engine) as s:
        count = len(s.scalars(select(ChannelIdentity).where(ChannelIdentity.person_id == person_id)).all())
    assert count == 2


def test_an_email_or_number_of_a_classified_contact_is_a_409_naming_them(client: TestClient) -> None:
    first = _add(client, name="Pieter Bakker", email="pieter@bouw.test").json()
    clash = _add(client, name="Someone Else", category="tenant", email="pieter@bouw.test")
    assert clash.status_code == 409
    assert "Pieter Bakker" in clash.json()["detail"]
    assert len(client.get(CONTACTS).json()) == 1
    assert first["id"] in {c["id"] for c in client.get(CONTACTS).json()}


def test_an_email_and_a_phone_of_two_different_people_cannot_be_joined(book: Book, client: TestClient) -> None:
    _message_person(book, Channel.gmail, "a@x.test")
    _message_person(book, Channel.whatsapp, "+31622222222")
    assert _add(client, email="a@x.test", phone="0622222222").status_code == 409


@pytest.mark.parametrize(
    "body",
    [
        {"email": "not-an-email"},
        {"phone": "12"},
        {"phone": "hello"},
        {"category": "landlord"},
        {"name": "   "},
        {"name": ""},
    ],
)
def test_unusable_input_is_a_422_and_stores_nothing(client: TestClient, body: dict[str, str]) -> None:
    assert _add(client, **body).status_code == 422
    assert client.get(CONTACTS).json() == []


def test_a_contact_without_email_or_phone_is_allowed(client: TestClient) -> None:
    created = _add(client, name="Gemeente Utrecht", category="municipal").json()
    assert (created["email"], created["phone"]) == ("", "")


def test_the_same_address_can_belong_to_different_contacts_in_different_companies(
    book: Book, client: TestClient
) -> None:
    theirs = _message_person(book, Channel.gmail, "shared@x.test", company=book.other_company)
    mine = _add(client, email="shared@x.test").json()["id"]
    assert mine != str(theirs)
    with Session(book.engine) as s:
        still_theirs = s.get(Person, theirs)
        assert still_theirs is not None
        assert still_theirs.kind is PersonKind.other


def test_a_contact_from_another_company_is_never_listed_or_editable(book: Book, client: TestClient) -> None:
    theirs = _message_person(book, Channel.gmail, "their@x.test", company=book.other_company)
    assert client.get(CONTACTS).json() == []
    response = client.patch(f"{CONTACTS}/{theirs}", json={"name": "Mine now"}, headers=CSRF)
    assert response.status_code == 404
    with Session(book.engine) as s:
        person = s.get(Person, theirs)
        assert person is not None
        assert person.display_name == "their@x.test"


def test_a_contact_created_from_a_message_can_be_named_and_reclassified(book: Book, client: TestClient) -> None:
    person_id = _message_person(book, Channel.gmail, "pieter@bouw.test")
    response = client.patch(
        f"{CONTACTS}/{person_id}",
        json={"name": "  Pieter   Bakker ", "category": "contractor", "trade": "roofer"},
        headers=CSRF,
    )
    assert response.status_code == 200
    body = response.json()
    assert (body["name"], body["category"], body["tradeOrRole"], body["unclassified"]) == (
        "Pieter Bakker",
        "contractor",
        "Roofer Contractor",
        False,
    )
    assert client.get(CONTACTS).json()[0]["email"] == "pieter@bouw.test"


def test_a_contact_managed_by_brixx_cannot_be_edited_here(book: Book, client: TestClient) -> None:
    with Session(book.engine) as s, s.begin():
        person = Person(
            company_id=book.company, kind=PersonKind.tenant, display_name="Anouk", brixx_ref="R1", valid_from=SINCE
        )
        s.add(person)
        s.flush()
        person_id = person.id
    response = client.patch(f"{CONTACTS}/{person_id}", json={"name": "Renamed"}, headers=CSRF)
    assert response.status_code == 409
    assert "BRIXX" in response.json()["detail"]
    assert client.get(CONTACTS).json()[0]["source"] == "brixx"


def test_editing_an_unknown_contact_or_with_a_bad_category_fails_cleanly(client: TestClient) -> None:
    assert client.patch(f"{CONTACTS}/{uuid4()}", json={"name": "X"}, headers=CSRF).status_code == 404
    assert client.patch(f"{CONTACTS}/{uuid4()}", json={"category": "landlord"}, headers=CSRF).status_code == 422


def test_adding_a_contact_needs_the_client_header(client: TestClient) -> None:
    assert client.post(CONTACTS, json={"name": "X", "category": "other"}).status_code == 403


def test_a_profile_without_the_contacts_section_cannot_list_or_add(book: Book) -> None:
    clerk = add_person_to_team(
        book.engine, book.company, f"c-{uuid4().hex[:6]}@t.test", role="member", sections=["tenants"]
    )
    with signed_in(book.app, book.settings, clerk) as client:
        assert client.get(CONTACTS).status_code == 403
        assert _add(client).status_code == 403


def test_two_contacts_with_the_same_name_are_both_listed(client: TestClient) -> None:
    first = _add(client, name="Jan Bakker", trade="plumber", email="jan1@x.test").json()["id"]
    second = _add(client, name="Jan Bakker", trade="plumber", email="jan2@x.test").json()["id"]
    assert {c["id"] for c in client.get(CONTACTS).json()} == {first, second}


def test_adding_a_known_sender_with_a_different_number_than_they_already_have_is_a_409(
    book: Book, client: TestClient
) -> None:
    person_id = _message_person(book, Channel.gmail, "pieter@bouw.test")
    with Session(book.engine) as s, s.begin():
        s.add(
            ChannelIdentity(
                company_id=book.company,
                person_id=person_id,
                channel=Channel.whatsapp,
                identity="+31633333333",
                valid_from=SINCE,
            )
        )
    clash = _add(client, name="Pieter", email="pieter@bouw.test", phone="0644444444")
    assert clash.status_code == 409
    assert "different phone number" in clash.json()["detail"]
    same = _add(client, name="Pieter", email="pieter@bouw.test", phone="0633333333")
    assert same.status_code == 201


def test_a_role_less_other_contact_counts_as_classified(client: TestClient) -> None:
    created = _add(client, name="Notary Smit", category="other", email="smit@notary.test").json()
    assert created["unclassified"] is False
    assert created["trade"] == "other"
    assert _add(client, name="Someone", category="tenant", email="smit@notary.test").status_code == 409


def test_the_real_trade_comes_back_so_editing_does_not_save_a_display_label(book: Book, client: TestClient) -> None:
    person_id = _message_person(book, Channel.gmail, "pieter@bouw.test")
    listed = client.get(CONTACTS).json()[0]
    assert (listed["trade"], listed["unitRole"], listed["unclassified"]) == ("", "Contact", True)
    client.patch(f"{CONTACTS}/{person_id}", json={"category": "contractor", "trade": "roofer"}, headers=CSRF)
    assert client.get(CONTACTS).json()[0]["trade"] == "roofer"


def test_a_person_with_a_lease_cannot_be_reclassified_away_from_tenant(book: Book, client: TestClient) -> None:
    from app.db.models import Lease, LeaseParty, Unit

    with Session(book.engine) as s, s.begin():
        person = Person(company_id=book.company, kind=PersonKind.tenant, display_name="Anouk", valid_from=SINCE)
        unit = Unit(company_id=book.company, label="4B", valid_from=SINCE)
        s.add_all([person, unit])
        s.flush()
        lease = Lease(company_id=book.company, unit_id=unit.id, valid_from=SINCE)
        s.add(lease)
        s.flush()
        s.add(LeaseParty(company_id=book.company, lease_id=lease.id, person_id=person.id, role="tenant"))
        person_id = person.id
    response = client.patch(f"{CONTACTS}/{person_id}", json={"category": "contractor"}, headers=CSRF)
    assert response.status_code == 409
    assert "lease" in response.json()["detail"]
    assert client.patch(f"{CONTACTS}/{person_id}", json={"name": "Anouk de V"}, headers=CSRF).status_code == 200
