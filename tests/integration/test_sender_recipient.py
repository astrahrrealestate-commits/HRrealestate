"""The tenant recipient comes from the DB: the case person's current identity, never anyone else."""

from datetime import UTC, date, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from sqlalchemy.orm import Session

from app.contracts import Category, Channel, Direction, Urgency
from app.db.enums import LinkMethod, PersonKind
from app.db.models import (
    Case,
    CaseLink,
    ChannelAccount,
    ChannelIdentity,
    Company,
    MessageRow,
    OwnerAccount,
    Person,
    RawEvent,
)
from app.sender.recipient import tenant_recipient, whatsapp_window_open
from app.sender.targets import SendBlockedError

pytestmark = pytest.mark.integration
NOW = datetime(2026, 10, 15, 12, 0, tzinfo=UTC)
TENANT = "+31612345678"
VALID_FROM = date(2026, 1, 1)


def _person(db: Session, company: Company, identity: str | None, channel: Channel = Channel.whatsapp) -> Person:
    person = Person(company_id=company.id, kind=PersonKind.tenant, display_name="Huurder", valid_from=VALID_FROM)
    db.add(person)
    db.flush()
    if identity:
        db.add(ChannelIdentity(company_id=company.id, person_id=person.id, channel=channel, identity=identity,
                               valid_from=VALID_FROM))  # fmt: skip
    return person


def _case(db: Session, company: Company, person: Person | None) -> Case:
    case = Case(company_id=company.id, category=Category.maintenance, urgency=Urgency.normal,
                primary_person_id=person.id if person else None)  # fmt: skip
    db.add(case)
    db.flush()
    return case


def _inbound(
    db: Session, case: Case, sender: str, channel: Channel = Channel.whatsapp, age: timedelta = timedelta(hours=1),
    direction: Direction = Direction.inbound,
) -> MessageRow:  # fmt: skip
    raw = RawEvent(company_id=case.company_id, provider=channel, provider_msg_id=f"m-{uuid4()}", payload={})
    db.add(raw)
    db.flush()
    msg = MessageRow(
        company_id=case.company_id, raw_event_id=raw.id, channel=channel, provider_msg_id=raw.provider_msg_id,
        thread_ref="t1", sender_identity=sender, direction=direction, sent_at=NOW - age, created_at=NOW - age,
        text="hallo",
    )  # fmt: skip
    db.add(msg)
    db.flush()
    db.add(CaseLink(company_id=case.company_id, case_id=case.id, message_id=msg.id, method=LinkMethod.new_case))
    db.flush()
    return msg


def _blocked(db: Session, company_id: UUID, case: Case, reason: str, channel: Channel = Channel.whatsapp) -> None:
    with pytest.raises(SendBlockedError, match=reason):
        tenant_recipient(db, company_id, case.id, channel)


def test_identity_of_the_case_person_is_returned(db: Session, company: Company) -> None:
    case = _case(db, company, _person(db, company, TENANT))
    msg = _inbound(db, case, TENANT)
    assert tenant_recipient(db, company.id, case.id, Channel.whatsapp) == (msg, TENANT)


def test_newer_message_from_another_number_is_skipped_for_the_contacts_own(db: Session, company: Company) -> None:
    case = _case(db, company, _person(db, company, TENANT))
    older = _inbound(db, case, TENANT, age=timedelta(hours=3))
    _inbound(db, case, "+31699999999", age=timedelta(hours=1))
    msg, identity = tenant_recipient(db, company.id, case.id, Channel.whatsapp)
    assert (msg, identity) == (older, TENANT)
    assert whatsapp_window_open(msg, NOW)
    assert not whatsapp_window_open(msg, NOW + timedelta(hours=21))  # the window runs from the contact's message


def test_only_a_non_primary_sender_wrote_is_blocked(db: Session, company: Company) -> None:
    case = _case(db, company, _person(db, company, TENANT))
    _inbound(db, case, "+31699999999")
    _blocked(db, company.id, case, "no inbound message from the case contact")


def test_spoofed_sender_is_never_returned_even_if_newest(db: Session, company: Company) -> None:
    case = _case(db, company, _person(db, company, TENANT))
    _inbound(db, case, "not-a-number-or-email", age=timedelta(minutes=1))
    _inbound(db, case, "+31699999999", age=timedelta(minutes=2))
    _blocked(db, company.id, case, "no inbound message from the case contact")


def test_other_companys_identity_row_does_not_authorize(db: Session, company: Company) -> None:
    other = Company(name="Other GmbH")
    db.add(other)
    db.flush()
    person = _person(db, company, None)  # no identity of its own in this company
    db.add(ChannelIdentity(company_id=other.id, person_id=person.id, channel=Channel.whatsapp, identity=TENANT,
                           valid_from=VALID_FROM))  # fmt: skip
    case = _case(db, company, person)
    _inbound(db, case, TENANT)
    _blocked(db, company.id, case, "no inbound message from the case contact")


def test_only_whatsapp_and_gmail_are_tenant_channels(db: Session, company: Company) -> None:
    case = _case(db, company, _person(db, company, TENANT))
    _blocked(db, company.id, case, "not a tenant reply channel", Channel.google_chat)


def test_expired_identity_is_blocked(db: Session, company: Company) -> None:
    person = _person(db, company, TENANT)
    case = _case(db, company, person)
    _inbound(db, case, TENANT)
    db.flush()
    ident = db.query(ChannelIdentity).filter_by(person_id=person.id).one()
    ident.valid_to = NOW.date() - timedelta(days=1)
    db.flush()
    _blocked(db, company.id, case, "no inbound message from the case contact")


def test_other_companys_case_is_not_found(db: Session, company: Company) -> None:
    other = Company(name="Other GmbH")
    db.add(other)
    db.flush()
    case = _case(db, company, _person(db, company, TENANT))
    _inbound(db, case, TENANT)
    _blocked(db, other.id, case, "case not found")


def test_identity_that_exists_only_in_the_other_company_is_blocked(db: Session, company: Company) -> None:
    other = Company(name="Other GmbH")
    db.add(other)
    db.flush()
    _person(db, other, TENANT)
    case = _case(db, company, _person(db, company, None))
    _inbound(db, case, TENANT)
    _blocked(db, company.id, case, "no inbound message from the case contact")


def test_identity_of_another_channel_does_not_count(db: Session, company: Company) -> None:
    case = _case(db, company, _person(db, company, TENANT, channel=Channel.gmail))
    _inbound(db, case, TENANT)
    _blocked(db, company.id, case, "no inbound message from the case contact")


def test_email_identity_is_case_insensitive(db: Session, company: Company) -> None:
    case = _case(db, company, _person(db, company, "huurder@example.test", channel=Channel.gmail))
    msg = _inbound(db, case, "Huurder@Example.TEST", channel=Channel.gmail)
    assert tenant_recipient(db, company.id, case.id, Channel.gmail) == (msg, "huurder@example.test")


def test_owner_own_number_never_qualifies(db: Session, company: Company) -> None:
    db.add(OwnerAccount(company_id=company.id, display_name="Harjot", whatsapp_e164="+31611111111"))
    case = _case(db, company, _person(db, company, "+31611111111"))
    _inbound(db, case, "+31611111111")
    _blocked(db, company.id, case, "no inbound message from the case contact")


def test_company_mailbox_never_qualifies(db: Session, company: Company) -> None:
    mailbox = f"verhuur-{uuid4().hex[:6]}@example.test"
    db.add(ChannelAccount(company_id=company.id, channel=Channel.gmail, address=mailbox))
    case = _case(db, company, _person(db, company, mailbox, channel=Channel.gmail))
    _inbound(db, case, mailbox, channel=Channel.gmail)
    _blocked(db, company.id, case, "no inbound message from the case contact", Channel.gmail)


def test_outbound_messages_never_qualify(db: Session, company: Company) -> None:
    case = _case(db, company, _person(db, company, TENANT))
    _inbound(db, case, TENANT, direction=Direction.outbound)
    _blocked(db, company.id, case, "no inbound message from the case contact")


def test_no_inbound_on_the_channel_is_blocked(db: Session, company: Company) -> None:
    case = _case(db, company, _person(db, company, TENANT))
    _inbound(db, case, TENANT, channel=Channel.gmail)
    _blocked(db, company.id, case, "no inbound message from the case contact")


def test_case_without_primary_person_is_blocked(db: Session, company: Company) -> None:
    case = _case(db, company, None)
    _inbound(db, case, TENANT)
    _blocked(db, company.id, case, "no contact person")


@pytest.mark.parametrize(("hours", "open_"), [(22, True), (23, False), (24, False)])
def test_window_from_inbound_receipt_time(db: Session, company: Company, hours: int, open_: bool) -> None:
    case = _case(db, company, _person(db, company, TENANT))
    _inbound(db, case, TENANT, age=timedelta(hours=hours))
    msg, _ = tenant_recipient(db, company.id, case.id, Channel.whatsapp)
    assert whatsapp_window_open(msg, NOW) is open_
