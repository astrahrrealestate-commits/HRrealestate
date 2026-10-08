"""Follow-up (#5) end to end at the DB level: approved request → wait → chaser draft → escalation."""

from datetime import UTC, date, datetime, timedelta
from uuid import UUID

import pytest
from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from app.contracts import ActionType, CaseState, Category, Channel, Direction, Urgency
from app.core.ids import new_id
from app.core.settings import Settings
from app.db.enums import ActionStatus, LinkMethod, PersonKind, WaitStatus
from app.db.models import ActionRow, Approval, Company, MessageRow, Person, RawEvent, WaitRow
from app.pipeline import case_repo, followups, work_repo

pytestmark = pytest.mark.integration
NOW = datetime(2026, 10, 5, 8, 0, tzinfo=UTC)  # a Monday


def _case(engine: Engine, cid: UUID, state: CaseState = CaseState.open) -> tuple[UUID, UUID, UUID]:
    with Session(engine) as s, s.begin():
        tenant = Person(company_id=cid, kind=PersonKind.tenant, display_name="Sanne", valid_from=date(2026, 1, 1))
        plumber = Person(
            company_id=cid,
            kind=PersonKind.contractor,
            display_name="Jansen",
            trade="plumber",
            valid_from=date(2026, 1, 1),
        )
        raw = RawEvent(company_id=cid, provider=Channel.whatsapp, provider_msg_id=str(new_id()), payload={})
        s.add_all([tenant, plumber, raw])
        s.flush()
        msg = MessageRow(
            company_id=cid,
            raw_event_id=raw.id,
            channel=Channel.whatsapp,
            provider_msg_id=raw.provider_msg_id,
            thread_ref="+31612345678",
            sender_identity="+31612345678",
            direction=Direction.inbound,
            sent_at=NOW,
            text="Lek",
            person_id=tenant.id,
        )
        s.add(msg)
        s.flush()
        case_id = case_repo.create_case(s, cid, tenant.id, Category.maintenance, Urgency.normal)
        case_repo.link_message(s, cid, case_id, msg.id, LinkMethod.new_case, None)
        if state is not CaseState.open:
            case_repo.transition(s, cid, case_id, state, actor="system")
        return case_id, tenant.id, plumber.id


def _executed(engine: Engine, cid: UUID, case_id: UUID, kind: ActionType, payload: dict[str, object]) -> UUID:
    with Session(engine) as s, s.begin():
        a = ActionRow(
            company_id=cid,
            case_id=case_id,
            type=kind,
            payload=payload,
            rationale="r",
            context_ref=[],
            status=ActionStatus.executed,
        )
        s.add(a)
        s.flush()
        return a.id


def _wait(engine: Engine, cid: UUID, wait_id: UUID) -> WaitRow:
    with Session(engine) as s:
        return work_repo.get_wait(s, cid, wait_id)


def test_contractor_request_opens_wait_three_business_days_out(
    migrated_engine: Engine, committed_company: Company
) -> None:
    cid = committed_company.id
    case_id, _, plumber = _case(migrated_engine, cid)
    payload = {"kind": "request_contractor", "contractor_person_id": str(plumber), "body_variants": ["A", "B"]}
    action_id = _executed(migrated_engine, cid, case_id, ActionType.request_contractor, payload)
    wait_id = followups.open_waits_after_execute(migrated_engine, action_id, now=NOW)
    assert wait_id is not None
    wait = _wait(migrated_engine, cid, wait_id)
    assert (wait.party_person_id, wait.expected_by) == (plumber, datetime(2026, 10, 8, 8, 0, tzinfo=UTC))


def test_plain_reply_opens_no_wait_unless_case_waits_on_third_party(
    migrated_engine: Engine, committed_company: Company
) -> None:
    cid = committed_company.id
    payload = {"kind": "reply_draft", "channel": "whatsapp", "subject": None, "body_variants": ["A", "B"]}
    open_case, _, _ = _case(migrated_engine, cid)
    assert (
        followups.open_waits_after_execute(
            migrated_engine, _executed(migrated_engine, cid, open_case, ActionType.reply_draft, payload), now=NOW
        )
        is None
    )
    waiting_case, tenant, _ = _case(migrated_engine, cid, CaseState.waiting_on_third_party)
    wid = followups.open_waits_after_execute(
        migrated_engine, _executed(migrated_engine, cid, waiting_case, ActionType.reply_draft, payload), now=NOW
    )
    assert wid is not None
    assert _wait(migrated_engine, cid, wid).party_person_id == tenant


def test_due_wait_chases_twice_then_escalates_and_stale_timers_do_nothing(
    migrated_engine: Engine, committed_company: Company, test_settings: Settings
) -> None:
    cid = committed_company.id
    case_id, tenant, _ = _case(migrated_engine, cid, CaseState.waiting_on_third_party)
    with Session(migrated_engine) as s, s.begin():
        wid = work_repo.open_wait(s, cid, case_id, tenant, about="Foto van de lekkage", expected_by=NOW)
    due = NOW + timedelta(minutes=1)
    first = followups.handle_wait_due(migrated_engine, test_settings, cid, wid, step=0, now=due)
    # reclaimed timer (crash before the card was sent): same approval again, so the card still goes out once
    assert followups.handle_wait_due(migrated_engine, test_settings, cid, wid, step=0, now=due) == first
    later = _wait(migrated_engine, cid, wid).expected_by + timedelta(minutes=1)
    second = followups.handle_wait_due(migrated_engine, test_settings, cid, wid, step=1, now=later)
    last = _wait(migrated_engine, cid, wid).expected_by + timedelta(minutes=1)
    third = followups.handle_wait_due(migrated_engine, test_settings, cid, wid, step=2, now=last)
    assert None not in (first, second, third)
    with Session(migrated_engine) as s:
        types = s.scalars(
            select(ActionRow.type)
            .join(Approval, Approval.action_id == ActionRow.id)
            .where(ActionRow.case_id == case_id)
            .order_by(Approval.created_at)
        ).all()
    assert list(types) == [ActionType.reply_draft, ActionType.reply_draft, ActionType.escalate]
    assert _wait(migrated_engine, cid, wid).status is WaitStatus.escalated
