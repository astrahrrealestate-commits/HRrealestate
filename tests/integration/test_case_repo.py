"""Case repository: thread lookup, open candidates, idempotent linking, summary compare-and-swap, transitions."""

from datetime import UTC, date, datetime, timedelta

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.contracts import CaseState, Category, Channel, Direction, Urgency
from app.core.errors import IllegalTransitionError, NotFoundError
from app.core.ids import new_id
from app.db.enums import CaseEventKind, LinkMethod, PersonKind
from app.db.models import CaseEvent, CaseLink, Company, MessageRow, Person, RawEvent
from app.pipeline import case_repo

pytestmark = pytest.mark.integration
NOW = datetime(2026, 10, 7, 9, 0, tzinfo=UTC)


def _person(db: Session, company: Company) -> Person:
    p = Person(company_id=company.id, kind=PersonKind.other, display_name="Sanne", valid_from=date(2026, 1, 1))
    db.add(p)
    db.flush()
    return p


def _msg(db: Session, company: Company, person: Person, *, thread: str | None, at: datetime = NOW,
         channel: Channel = Channel.gmail) -> MessageRow:  # fmt: skip
    raw = RawEvent(company_id=company.id, provider=channel, provider_msg_id=str(new_id()), payload={})
    db.add(raw)
    db.flush()
    m = MessageRow(
        company_id=company.id, raw_event_id=raw.id, channel=channel, provider_msg_id=raw.provider_msg_id,
        thread_ref=thread, sender_identity="sanne@example.test", direction=Direction.inbound, sent_at=at,
        text="Lekkage", person_id=person.id,
    )  # fmt: skip
    db.add(m)
    db.flush()
    return m


def test_create_and_link_is_idempotent(db: Session, company: Company) -> None:
    person = _person(db, company)
    msg = _msg(db, company, person, thread="t1")
    case_id = case_repo.create_case(db, company.id, person.id, Category.maintenance, Urgency.high)
    case_repo.link_message(db, company.id, case_id, msg.id, LinkMethod.new_case, None)
    case_repo.link_message(db, company.id, case_id, msg.id, LinkMethod.new_case, None)
    assert db.scalar(select(func.count()).select_from(CaseLink).where(CaseLink.message_id == msg.id)) == 1
    kinds = db.scalars(select(CaseEvent.kind).where(CaseEvent.case_id == case_id)).all()
    assert kinds.count(CaseEventKind.link) == 1
    assert case_repo.case_of_message(db, company.id, msg.id) == case_id


def test_thread_case_finds_gmail_thread_but_not_closed_cases(db: Session, company: Company) -> None:
    person = _person(db, company)
    first = _msg(db, company, person, thread="gm-thread")
    case_id = case_repo.create_case(db, company.id, person.id, Category.maintenance, Urgency.normal)
    case_repo.link_message(db, company.id, case_id, first.id, LinkMethod.new_case, None)
    later = _msg(db, company, person, thread="gm-thread", at=NOW + timedelta(days=30))
    assert case_repo.thread_case(db, company.id, later) == case_id
    case_repo.transition(db, company.id, case_id, CaseState.closed, actor="owner")
    assert case_repo.thread_case(db, company.id, later) is None


def test_whatsapp_thread_window_is_72_hours(db: Session, company: Company) -> None:
    person = _person(db, company)
    first = _msg(db, company, person, thread="+31612345678", channel=Channel.whatsapp)
    case_id = case_repo.create_case(db, company.id, person.id, Category.payment, Urgency.normal)
    case_repo.link_message(db, company.id, case_id, first.id, LinkMethod.new_case, None)
    soon = _msg(db, company, person, thread="+31612345678", at=NOW + timedelta(hours=71), channel=Channel.whatsapp)
    late = _msg(db, company, person, thread="+31612345678", at=NOW + timedelta(hours=80), channel=Channel.whatsapp)
    assert case_repo.thread_case(db, company.id, soon) == case_id
    assert case_repo.thread_case(db, company.id, late) is None


def test_open_candidates_for_person(db: Session, company: Company) -> None:
    person = _person(db, company)
    msg = _msg(db, company, person, thread=None)
    open_id = case_repo.create_case(db, company.id, person.id, Category.maintenance, Urgency.normal)
    case_repo.link_message(db, company.id, open_id, msg.id, LinkMethod.new_case, None)
    resolved = case_repo.create_case(db, company.id, person.id, Category.payment, Urgency.low)
    case_repo.transition(db, company.id, resolved, CaseState.resolved, actor="owner")
    cands = case_repo.open_candidates(db, company.id, person.id)
    assert [(c.case_id, c.category, c.last_message_at) for c in cands] == [(open_id, Category.maintenance, NOW)]


def test_summary_compare_and_swap(db: Session, company: Company) -> None:
    person = _person(db, company)
    case_id = case_repo.create_case(db, company.id, person.id, Category.other, Urgency.normal)
    assert case_repo.update_summary(db, company.id, case_id, "first", expected_version=0) is True
    assert case_repo.update_summary(db, company.id, case_id, "stale", expected_version=0) is False
    case = case_repo.get_case(db, company.id, case_id)
    assert (case.summary, case.summary_version) == ("first", 1)


def test_transition_rules_and_tenant_scope(db: Session, company: Company) -> None:
    person = _person(db, company)
    case_id = case_repo.create_case(db, company.id, person.id, Category.other, Urgency.normal)
    case_repo.transition(db, company.id, case_id, CaseState.closed, actor="owner")
    with pytest.raises(IllegalTransitionError):
        case_repo.transition(db, company.id, case_id, CaseState.open, actor="owner")
    with pytest.raises(NotFoundError):
        case_repo.get_case(db, new_id(), case_id)
