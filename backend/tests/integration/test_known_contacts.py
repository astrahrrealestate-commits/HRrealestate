"""Who feeds the AI case pipeline (ADR 0015): the directory decides, never the message."""

from datetime import UTC, date, datetime
from uuid import UUID

import pytest
from sqlalchemy.orm import Session

from app.contracts import CaseState, Category, Channel, Direction, Urgency
from app.db.enums import LinkMethod, PersonKind, RawEventStatus
from app.db.known_contacts import feeds_pipeline, is_known_contact
from app.db.models import Case, CaseLink, ChannelIdentity, Company, MessageRow, OwnerAccount, Person, RawEvent

pytestmark = pytest.mark.integration
NUMBER, OWNER = "+31611112222", "+31699990000"
DAY = date(2026, 1, 1)


def _person(
    db: Session,
    company: Company,
    kind: PersonKind,
    *,
    brixx_ref: str | None = None,
    trade: str | None = None,
    ended: bool = False,
    identity_closed: bool = False,
) -> Person:
    person = Person(
        company_id=company.id,
        kind=kind,
        display_name="Someone",
        brixx_ref=brixx_ref,
        trade=trade,
        valid_from=DAY,
        valid_to=DAY if ended else None,
    )
    db.add(person)
    db.flush()
    db.add(
        ChannelIdentity(
            company_id=company.id,
            person_id=person.id,
            channel=Channel.whatsapp,
            identity=NUMBER,
            valid_from=DAY,
            valid_to=DAY if identity_closed else None,
        )
    )
    db.flush()
    return person


def _known(db: Session, company: Company, identity: str = NUMBER) -> bool:
    return is_known_contact(db, company.id, Channel.whatsapp, identity)


@pytest.mark.parametrize("kind", [PersonKind.tenant, PersonKind.contractor, PersonKind.owner])
def test_a_real_kind_is_known(db: Session, company: Company, kind: PersonKind) -> None:
    _person(db, company, kind)
    assert _known(db, company)


def test_a_person_the_directory_only_auto_created_is_not_known(db: Session, company: Company) -> None:
    _person(db, company, PersonKind.other)
    assert not _known(db, company)


def test_a_brixx_person_and_a_hand_added_utility_are_known(db: Session, company: Company) -> None:
    _person(db, company, PersonKind.other, brixx_ref="BX-9")
    assert _known(db, company)


def test_a_trade_contact_is_known(db: Session, company: Company) -> None:
    _person(db, company, PersonKind.other, trade="utility")
    assert _known(db, company)


def test_an_ended_tenant_is_still_known(db: Session, company: Company) -> None:
    """His lease just ended and he writes about the deposit: that must not vanish into Chats."""
    _person(db, company, PersonKind.tenant, ended=True)
    assert _known(db, company)


def test_a_closed_identity_is_not_known(db: Session, company: Company) -> None:
    _person(db, company, PersonKind.tenant, identity_closed=True)
    assert not _known(db, company)


def test_another_companys_contact_is_not_known(db: Session, company: Company) -> None:
    other = Company(name="Other")
    db.add(other)
    db.flush()
    _person(db, other, PersonKind.tenant)
    assert not _known(db, company)


def test_a_person_with_a_case_is_known(db: Session, company: Company) -> None:
    person = _person(db, company, PersonKind.other)
    db.add(
        Case(
            company_id=company.id,
            category=Category.other,
            urgency=Urgency.normal,
            state=CaseState.open,
            primary_person_id=person.id,
        )
    )
    db.flush()
    assert _known(db, company)


def _linked_message(db: Session, company: Company) -> None:
    raw = RawEvent(
        company_id=company.id,
        provider=Channel.whatsapp,
        provider_msg_id="wamid.X",
        payload={},
        status=RawEventStatus.processed,
    )
    db.add(raw)
    db.flush()
    msg = MessageRow(
        company_id=company.id,
        raw_event_id=raw.id,
        channel=Channel.whatsapp,
        provider_msg_id="wamid.X",
        thread_ref=NUMBER,
        sender_identity="dashboard",
        direction=Direction.outbound,
        sent_at=datetime(2026, 1, 2, tzinfo=UTC),
        text="Wij sturen een monteur.",
        meta={},
    )
    case = Case(company_id=company.id, category=Category.other, urgency=Urgency.normal, state=CaseState.open)
    db.add_all([msg, case])
    db.flush()
    db.add(
        CaseLink(company_id=company.id, case_id=case.id, message_id=msg.id, method=LinkMethod.thread, confidence=1.0)
    )
    db.flush()


def test_a_number_whose_conversation_a_case_contains_stays_known(db: Session, company: Company) -> None:
    """A third party Harjot approved a message to, with no person of their own, answers: it is part of the case."""
    _linked_message(db, company)
    assert _known(db, company)


def test_the_owner_feeds_the_pipeline_router_and_a_stranger_does_not(db: Session, company: Company) -> None:
    db.add(OwnerAccount(company_id=company.id, display_name="H", whatsapp_e164=OWNER, email="h@x.test"))
    db.flush()
    assert feeds_pipeline(db, company.id, Channel.whatsapp, OWNER)
    assert not feeds_pipeline(db, company.id, Channel.whatsapp, "+31600000000")


def test_a_company_id_is_required_to_resolve_anyone(db: Session, company: Company) -> None:
    _person(db, company, PersonKind.tenant)
    assert not is_known_contact(db, UUID(int=0), Channel.whatsapp, NUMBER)
