"""Contacts: only the signed-in company's directory and messages, truthful lease facts, and no pretend sends."""

from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, date, datetime
from unittest.mock import MagicMock
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, func, select
from sqlalchemy.orm import Session

from app.api.v1.auth import Principal
from app.contracts import Channel, Direction
from app.core.settings import Settings
from app.db.enums import PersonKind
from app.db.models import ChannelIdentity, Company, Lease, LeaseParty, MessageRow, Person, RawEvent, Send, Unit
from app.main import create_app
from tests.api_auth import as_owner
from tests.integration.conftest import purge_company

pytestmark = pytest.mark.integration
WHEN = datetime(2026, 11, 1, 10, 0, tzinfo=UTC)


@dataclass
class Book:
    client: TestClient
    engine: Engine
    my_company: UUID
    my_tenant: UUID
    their_tenant: UUID
    their_email: str


def _person(s: Session, company_id: UUID, name: str, email: str, kind: PersonKind = PersonKind.tenant) -> UUID:
    person = Person(company_id=company_id, kind=kind, display_name=name, valid_from=date(2024, 1, 1))
    s.add(person)
    s.flush()
    s.add(
        ChannelIdentity(
            company_id=company_id,
            person_id=person.id,
            channel=Channel.gmail,
            identity=email,
            valid_from=date(2024, 1, 1),
        )
    )
    raw = RawEvent(company_id=company_id, provider=Channel.gmail, provider_msg_id=f"m-{uuid4()}", payload={})
    s.add(raw)
    s.flush()
    s.add(
        MessageRow(
            company_id=company_id, raw_event_id=raw.id, channel=Channel.gmail, provider_msg_id=raw.provider_msg_id,
            thread_ref=f"t-{uuid4()}", sender_identity=email, person_id=person.id, direction=Direction.inbound,
            sent_at=WHEN, text=f"private note from {name}",
        )
    )  # fmt: skip
    s.flush()
    return person.id


@pytest.fixture
def book(migrated_engine: Engine, pg_url: str) -> Iterator[Book]:
    tag = uuid4().hex[:6]
    with Session(migrated_engine) as s:
        a, b = Company(name="Book A"), Company(name="Book B")
        s.add_all([a, b])
        s.flush()
        ids = (a.id, b.id)
        mine = _person(s, ids[0], "Anouk de Vries", f"anouk-{tag}@a.test")
        theirs = _person(s, ids[1], "Bram Jansen", f"bram-{tag}@b.test")
        unit = Unit(
            company_id=ids[0], label="Singel 5-A", address="Singel 5-A, 1012 AB Amsterdam", valid_from=date(2024, 1, 1)
        )
        s.add(unit)
        s.flush()
        lease = Lease(company_id=ids[0], unit_id=unit.id, valid_from=date(2025, 3, 1), valid_to=date(2026, 2, 28))
        s.add(lease)
        s.flush()
        s.add(LeaseParty(company_id=ids[0], lease_id=lease.id, person_id=mine, role="tenant"))
        s.commit()
    settings = Settings(database_url=pg_url, env="test", _env_file=None)  # type: ignore[call-arg]
    owner = Principal(company_id=ids[0], owner_id=uuid4(), email="harjot@example.test")
    app = as_owner(create_app(settings, engine=migrated_engine, workflow_client=MagicMock()), owner)
    with TestClient(app) as client:
        yield Book(client, migrated_engine, ids[0], mine, theirs, f"bram-{tag}@b.test")
    for company_id in ids:
        purge_company(migrated_engine, company_id)


def test_the_directory_lists_only_the_owners_company(book: Book) -> None:
    people = book.client.get("/api/contacts").json()
    assert [p["name"] for p in people] == ["Anouk de Vries"]
    assert "Bram" not in str(people)


def test_a_tenants_unit_and_agreement_come_from_the_lease_not_from_a_template(book: Book) -> None:
    [anouk] = book.client.get("/api/contacts").json()
    assert anouk["unitRole"] == "Singel 5-A"
    assert anouk["propertyAddress"] == "Singel 5-A, 1012 AB Amsterdam"
    assert anouk["agreementPeriod"] == "01 Mar 2025 — 28 Feb 2026"
    assert "Keizersgracht" not in str(anouk)
    assert "rating" not in anouk


def test_a_contact_without_a_lease_shows_blanks_instead_of_invented_facts(book: Book) -> None:
    with Session(book.engine) as s:
        s.query(LeaseParty).filter(LeaseParty.company_id == book.my_company).delete()
        s.commit()
    [anouk] = book.client.get("/api/contacts").json()
    assert (anouk["propertyAddress"], anouk["agreementPeriod"]) == ("", "")


def test_communications_never_return_another_companys_messages(book: Book) -> None:
    by_id = book.client.get(f"/api/contacts/{book.their_tenant}/communications")
    by_address = book.client.get(f"/api/contacts/anything/communications?email={book.their_email}")
    for response in (by_id, by_address):
        assert response.status_code == 200
        assert "private note from Bram" not in response.text
        assert response.json()["emails"] == []


def test_the_owners_own_communications_still_load(book: Book) -> None:
    body = book.client.get(f"/api/contacts/{book.my_tenant}/communications").json()
    assert any("private note from Anouk" in e["body"] for e in body["emails"])


def _written(book: Book) -> tuple[int, int]:
    with Session(book.engine) as s:
        messages = s.scalar(
            select(func.count()).select_from(MessageRow).where(MessageRow.direction == Direction.outbound)
        )
        sends = s.scalar(select(func.count()).select_from(Send))
    return messages or 0, sends or 0


def test_the_pretend_send_routes_refuse_and_write_nothing(book: Book) -> None:
    before = _written(book)
    wa = book.client.post(f"/api/contacts/{book.my_tenant}/whatsapp/send", json={"text": "hi"})
    mail = book.client.post(
        f"/api/contacts/{book.my_tenant}/messages/{uuid4()}/reply-mail", json={"subject": "s", "body": "b"}
    )
    assert (wa.status_code, mail.status_code) == (501, 501)
    assert "approve it in the inbox" in wa.json()["detail"]
    assert _written(book) == before
