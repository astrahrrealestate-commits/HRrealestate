"""Inbox threads label the sender from the directory: only a tenant is a Tenant with a unit; anyone else is a Contact
shown by property or organisation, never "Unassigned Unit" (spec 2026-11-24-sender-roles-design)."""

from collections.abc import Callable, Iterator
from typing import Any
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine
from sqlalchemy.orm import Session

from app.api.v1.auth import Principal
from app.core.settings import Settings
from app.db.enums import PersonKind
from app.db.models import (
    ActionRevision,
    ActionRow,
    Approval,
    Case,
    CaseEvent,
    CaseLink,
    Company,
    OwnerFeed,
    Person,
    Send,
    TaskRow,
    UnderstandingRow,
)
from app.db.models.ingestion import MessageRow, RawEvent
from app.main import create_app
from tests.api_auth import as_owner
from tests.integration.test_inbox_maintenance_approve import T0, FakeClient, _seed

pytestmark = pytest.mark.integration

Thread = Callable[..., dict[str, Any]]


@pytest.fixture
def thread_of(migrated_engine: Engine, pg_url: str) -> Iterator[Thread]:
    """`thread_of(sender, person_kind=None, trade=None)` seeds one case from `sender` and returns its inbox thread."""
    company_ids: list[UUID] = []
    clients: list[TestClient] = []

    def make(sender: str, person_kind: PersonKind | None = None, trade: str | None = None) -> dict[str, Any]:
        with Session(migrated_engine) as s:
            company = Company(name="Sender roles")
            s.add(company)
            s.flush()
            case_id, _, _ = _seed(s, company, suspicious=False)
            s.query(MessageRow).filter(MessageRow.company_id == company.id).update({"sender_identity": sender})
            if person_kind is not None:
                person = Person(
                    company_id=company.id, kind=person_kind, display_name="Sender", trade=trade, valid_from=T0.date()
                )
                s.add(person)
                s.flush()
                s.get(Case, case_id).primary_person_id = person.id  # type: ignore[union-attr]
            s.commit()
            company_ids.append(company.id)
            settings = Settings(database_url=pg_url, env="test", _env_file=None)  # type: ignore[call-arg]
            owner = Principal(company_id=company.id, owner_id=uuid4(), email="harjot@example.test")
            app = create_app(settings, engine=migrated_engine, workflow_client=FakeClient())
            client = TestClient(as_owner(app, owner))
            client.__enter__()
            clients.append(client)
            [thread] = client.get("/api/inbox/threads").json()["threads"]
            return thread  # type: ignore[no-any-return]

    yield make
    for client in clients:
        client.__exit__(None, None, None)
    with Session(migrated_engine) as s:
        for company_id in company_ids:
            s.query(Case).filter(Case.company_id == company_id).update({"primary_person_id": None})
            for model in (
                OwnerFeed, ActionRevision, UnderstandingRow, CaseLink, MessageRow, RawEvent, Approval, Send, TaskRow,
                ActionRow, CaseEvent, Case, Person,
            ):  # fmt: skip
                s.query(model).filter(model.company_id == company_id).delete(synchronize_session=False)
            s.query(Company).filter(Company.id == company_id).delete()
        s.commit()


def test_an_unknown_sender_is_a_contact_shown_by_organisation(thread_of: Thread) -> None:
    thread = thread_of("klaassen@pactadvocaten.nl")
    assert (thread["audience"], thread["recipientRole"], thread["recipientRoleDetail"]) == (
        "others",
        "contact",
        "Contact",
    )
    assert (thread["unit"], thread["sender"]["role"], thread["isUnregisteredSender"]) == (
        "pactadvocaten.nl",
        "Contact",
        False,
    )
    assert {m["sender"] for m in thread["messages"] if m["isIncoming"]} == {"contact"}


def test_a_free_mail_stranger_is_an_unlisted_contact(thread_of: Thread) -> None:
    assert thread_of("someone@gmail.com")["unit"] == "Unlisted contact"


def test_a_tenant_keeps_the_tenant_label_and_shows_a_missing_unit(thread_of: Thread) -> None:
    thread = thread_of("anouk@example.nl", PersonKind.tenant)
    assert (thread["audience"], thread["recipientRole"], thread["unit"]) == ("tenants", "tenant", "Unassigned Unit")
    assert {m["sender"] for m in thread["messages"] if m["isIncoming"]} == {"tenant"}


def test_a_contractor_keeps_the_trade(thread_of: Thread) -> None:
    thread = thread_of("info@loodgieter.nl", PersonKind.contractor, trade="plumber")
    assert (thread["audience"], thread["recipientRole"], thread["recipientRoleDetail"]) == (
        "contractors",
        "contractor",
        "Contractor · Plumber",
    )
    assert thread["unit"] == "loodgieter.nl"
