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
from app.contracts import Channel
from app.core.settings import Settings
from app.db.enums import PersonKind
from app.db.models import (
    ActionRevision,
    ActionRow,
    Approval,
    Case,
    CaseEvent,
    CaseLink,
    ChannelIdentity,
    Company,
    Lease,
    LeaseParty,
    OwnerFeed,
    Person,
    Send,
    TaskRow,
    UnderstandingRow,
    Unit,
)
from app.db.models.ingestion import MessageRow, RawEvent
from app.main import create_app
from tests.api_auth import as_owner
from tests.integration.test_inbox_maintenance_approve import T0, FakeClient, _seed

pytestmark = pytest.mark.integration

Thread = Callable[..., dict[str, Any]]


def _lease(s: Session, company_id: UUID, unit_label: str) -> None:
    unit = Unit(company_id=company_id, label=unit_label, valid_from=T0.date())
    holder = Person(company_id=company_id, kind=PersonKind.tenant, display_name="Anouk", valid_from=T0.date())
    s.add_all([unit, holder])
    s.flush()
    lease = Lease(company_id=company_id, unit_id=unit.id, valid_from=T0.date())
    s.add(lease)
    s.flush()
    s.add_all(
        [
            LeaseParty(company_id=company_id, lease_id=lease.id, person_id=holder.id, role="tenant"),
            ChannelIdentity(
                company_id=company_id,
                person_id=holder.id,
                channel=Channel.gmail,
                identity="anouk@example.nl",
                valid_from=T0.date(),
            ),
        ]
    )


@pytest.fixture
def thread_of(migrated_engine: Engine, pg_url: str) -> Iterator[Thread]:
    """`thread_of(sender, ...)` seeds one case from `sender` and returns its inbox thread.

    `role` is the model's stored `sender_role`, `text` replaces the message text, `leased_unit` adds a unit with a
    current lease held by another person (so a thread naming it can look like an unregistered tenant).
    """
    company_ids: list[UUID] = []
    clients: list[TestClient] = []

    def make(
        sender: str,
        person_kind: PersonKind | None = None,
        trade: str | None = None,
        *,
        role: str | None = None,
        text: str | None = None,
        leased_unit: str | None = None,
        flagged: bool = False,
    ) -> dict[str, Any]:
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
                s.query(MessageRow).filter(MessageRow.company_id == company.id).update({"person_id": person.id})
            if text is not None:
                s.query(MessageRow).filter(MessageRow.company_id == company.id).update({"text": text})
            for row in s.query(UnderstandingRow).filter(UnderstandingRow.company_id == company.id):
                row.body = {
                    **row.body,
                    "sender_role": role,
                    "suspicious": {"flag": flagged, "reason": "scanner: injection" if flagged else None},
                }
            if leased_unit is not None:
                _lease(s, company.id, leased_unit)
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
                ActionRow, CaseEvent, Case, LeaseParty, Lease, ChannelIdentity, Unit, Person,
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
    assert thread_of("someone@gmail.com")["unit"] == ""


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


def test_a_model_role_labels_an_unknown_sender(thread_of: Thread) -> None:
    thread = thread_of("klaassen@pactadvocaten.nl", role="legal")
    assert (thread["audience"], thread["recipientRole"], thread["recipientRoleDetail"]) == (
        "others",
        "contact",
        "Legal",
    )
    assert (thread["unit"], thread["sender"]["role"]) == ("pactadvocaten.nl", "Legal")


def test_a_prospect_is_an_inquiry(thread_of: Thread) -> None:
    thread = thread_of("lisa@gmail.com", role="prospect")
    assert (thread["audience"], thread["recipientRole"], thread["unit"]) == (
        "inquiries",
        "inquiry",
        "",
    )


def test_a_lawyer_naming_a_leased_unit_gets_no_link_to_tenant_banner(thread_of: Thread) -> None:
    text = "Betreft Duinvlietstraat 42: wij vertegenwoordigen de verhuurder."
    thread = thread_of("klaassen@pactadvocaten.nl", role="legal", text=text, leased_unit="Duinvlietstraat 42")
    assert (thread["unit"], thread["isUnregisteredSender"], thread["matchedTenant"]) == (
        "Duinvlietstraat 42",
        False,
        None,
    )


def test_an_unplaced_sender_naming_a_leased_unit_still_gets_the_banner(thread_of: Thread) -> None:
    text = "Ik woon op Duinvlietstraat 42 en de verwarming is kapot."
    for role in (None, "tenant"):
        thread = thread_of("anouks.partner@example.nl", role=role, text=text, leased_unit="Duinvlietstraat 42")
        assert thread["isUnregisteredSender"] is True
        assert thread["matchedTenant"]["name"] == "Anouk"
        assert thread["recipientRoleDetail"] == "Contact"


def test_the_directory_beats_the_model_role(thread_of: Thread) -> None:
    thread = thread_of("anouk@example.nl", PersonKind.tenant, role="legal")
    assert (thread["recipientRole"], thread["recipientRoleDetail"]) == ("tenant", "Tenant")


def test_a_flagged_mail_shows_no_role_even_if_the_stored_row_has_one(thread_of: Thread) -> None:
    """The injection scanner flags a mail after the model labelled it: a phishing "lawyer" stays a plain Contact."""
    thread = thread_of("klaassen@advocaten-secure-demo.nl", role="legal", flagged=True)
    assert (thread["recipientRoleDetail"], thread["audience"]) == ("Contact", "others")
