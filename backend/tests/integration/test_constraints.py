from collections.abc import Callable
from datetime import UTC, date, datetime

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.contracts import ActionType, Category, Channel, Direction, Urgency
from app.db.base import Base
from app.db.enums import ApprovalStatus, PersonKind
from app.db.models import (
    ActionRow,
    Approval,
    Case,
    ChannelIdentity,
    Company,
    MessageRow,
    Person,
    RawEvent,
    Send,
    Timer,
)

pytestmark = pytest.mark.integration


def _twice(db: Session, make: Callable[[], Base]) -> None:
    db.add(make())
    db.flush()
    db.add(make())
    with pytest.raises(IntegrityError):
        db.flush()


def test_raw_event_dedupe(db: Session, company: Company) -> None:
    _twice(
        db, lambda: RawEvent(company_id=company.id, provider=Channel.whatsapp, provider_msg_id="wamid.T1", payload={})
    )


def test_send_idempotency(db: Session, company: Company) -> None:
    _twice(db, lambda: Send(company_id=company.id, idempotency_key="exec:a:1", channel=Channel.gmail, target="t"))


def test_timer_dedupe_is_per_company(db: Session, company: Company) -> None:
    due = datetime(2026, 1, 1, tzinfo=UTC)
    other = Company(name="Other GmbH")
    db.add(other)
    db.flush()
    db.add(Timer(company_id=other.id, kind="briefing", due_at=due, payload={}, dedupe_key="b:2026-01-01"))
    _twice(db, lambda: Timer(company_id=company.id, kind="briefing", due_at=due, payload={}, dedupe_key="b:2026-01-01"))


def test_message_dedupe(db: Session, company: Company) -> None:
    raw = RawEvent(company_id=company.id, provider=Channel.whatsapp, provider_msg_id="wamid.M1", payload={})
    db.add(raw)
    db.flush()
    _twice(
        db,
        lambda: MessageRow(
            company_id=company.id,
            raw_event_id=raw.id,
            channel=Channel.whatsapp,
            provider_msg_id="wamid.M1",
            thread_ref=None,
            sender_identity="+4915550000001",
            direction=Direction.inbound,
            sent_at=datetime(2026, 1, 1, tzinfo=UTC),
            text="Hallo",
        ),
    )


def _action(db: Session, company: Company) -> ActionRow:
    case = Case(company_id=company.id, category=Category.maintenance, urgency=Urgency.normal)
    db.add(case)
    db.flush()
    action = ActionRow(
        company_id=company.id,
        case_id=case.id,
        type=ActionType.notify_owner,
        payload={"kind": "notify_owner", "text": "x"},
        rationale="r",
        context_ref=[],
    )
    db.add(action)
    db.flush()
    return action


def test_one_live_approval_per_draft_version(db: Session, company: Company) -> None:
    action = _action(db, company)
    _twice(db, lambda: Approval(company_id=company.id, action_id=action.id, draft_version=1))


def test_reask_allowed_after_expiry(db: Session, company: Company) -> None:
    action = _action(db, company)
    db.add(Approval(company_id=company.id, action_id=action.id, draft_version=1, status=ApprovalStatus.expired))
    db.add(Approval(company_id=company.id, action_id=action.id, draft_version=1))
    db.flush()


def test_identity_current_unique_but_history_allowed(db: Session, company: Company) -> None:
    p = Person(company_id=company.id, kind=PersonKind.tenant, display_name="Tenant 1", valid_from=date(2025, 1, 1))
    db.add(p)
    db.flush()

    def ident(valid_from: date, valid_to: date | None) -> ChannelIdentity:
        return ChannelIdentity(
            company_id=company.id,
            person_id=p.id,
            channel=Channel.whatsapp,
            identity="+4915550000001",
            valid_from=valid_from,
            valid_to=valid_to,
        )

    db.add_all([ident(date(2023, 1, 1), date(2023, 12, 31)), ident(date(2024, 1, 1), date(2024, 12, 31))])
    db.add(ident(date(2025, 1, 1), None))
    db.flush()
    db.add(ident(date(2025, 6, 1), None))
    with pytest.raises(IntegrityError):
        db.flush()


def test_enum_check_rejects_unknown_value(db: Session, company: Company) -> None:
    with pytest.raises(IntegrityError):
        db.execute(
            text(
                "INSERT INTO sends (id, company_id, idempotency_key, channel, target) "
                "VALUES (gen_random_uuid(), :c, 'k', 'telegram', 't')"
            ),
            {"c": company.id},
        )


def test_company_scoping_enforced_by_fk(db: Session) -> None:
    import uuid

    db.add(Send(company_id=uuid.uuid4(), idempotency_key="orphan", channel=Channel.gmail, target="t"))
    with pytest.raises(IntegrityError):
        db.flush()


def test_server_defaults_apply_to_raw_sql_inserts(db: Session, company: Company) -> None:
    row = db.execute(
        text(
            "INSERT INTO raw_events (id, company_id, provider, provider_msg_id, payload) "
            "VALUES (gen_random_uuid(), :c, 'gmail', 'm1', '{}') RETURNING status, attempts, created_at"
        ),
        {"c": company.id},
    ).one()
    assert row.status == "pending"
    assert row.attempts == 0
    assert row.created_at.tzinfo is not None
