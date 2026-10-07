"""Tasks (#6) and waiting-for items (#5): idempotent creation, short refs, close/snooze, wait timers."""

from datetime import UTC, date, datetime, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.contracts import ActionType, Category, Urgency
from app.core.errors import NotFoundError
from app.db.enums import PersonKind, TaskPriority, TaskStatus, TimerStatus, WaitStatus
from app.db.models import ActionRow, Company, Person, Timer
from app.pipeline import case_repo, work_repo

pytestmark = pytest.mark.integration
NOW = datetime(2026, 10, 7, 9, 0, tzinfo=UTC)


def _case(db: Session, company: Company) -> tuple:
    p = Person(
        company_id=company.id, kind=PersonKind.contractor, display_name="Loodgieter", valid_from=date(2026, 1, 1)
    )
    db.add(p)
    db.flush()
    return case_repo.create_case(db, company.id, None, Category.maintenance, Urgency.high), p.id


def _action(db: Session, company: Company, case_id) -> ActionRow:
    a = ActionRow(company_id=company.id, case_id=case_id, type=ActionType.notify_owner, payload={}, rationale="r",
                  context_ref=[])  # fmt: skip
    db.add(a)
    db.flush()
    return a


def test_task_per_action_source_is_created_once(db: Session, company: Company) -> None:
    case_id, _ = _case(db, company)
    action = _action(db, company, case_id)
    t1 = work_repo.create_task(db, company.id, title="Decide on reply", assignee="owner", source="approval",
                               case_id=case_id, action_id=action.id, due_at=NOW, priority=TaskPriority.p1)  # fmt: skip
    t2 = work_repo.create_task(db, company.id, title="dup", assignee="owner", source="approval", case_id=case_id,
                               action_id=action.id, due_at=NOW, priority=TaskPriority.p1)  # fmt: skip
    assert t1 == t2
    assert work_repo.close_action_tasks(db, company.id, action.id) == 1
    assert work_repo.open_tasks(db, company.id) == []


def test_open_tasks_order_and_short_ref_resolution(db: Session, company: Company) -> None:
    case_id, _ = _case(db, company)
    late = work_repo.create_task(db, company.id, title="later", assignee="owner", source="owner", case_id=case_id,
                                 due_at=NOW + timedelta(days=2), priority=TaskPriority.p3)  # fmt: skip
    urgent = work_repo.create_task(db, company.id, title="urgent", assignee="owner", source="owner", case_id=case_id,
                                   due_at=NOW + timedelta(hours=1), priority=TaskPriority.p1)  # fmt: skip
    assert [t.id for t in work_repo.open_tasks(db, company.id)] == [urgent, late]
    ref = work_repo.short_ref(urgent)
    assert len(ref) == 6
    assert work_repo.resolve_task(db, company.id, ref) == urgent
    with pytest.raises(NotFoundError):
        work_repo.resolve_task(db, company.id, "zzzzzz")


def test_complete_and_snooze(db: Session, company: Company) -> None:
    case_id, _ = _case(db, company)
    tid = work_repo.create_task(db, company.id, title="x", assignee="owner", source="owner", case_id=case_id)
    work_repo.snooze_task(db, company.id, tid, until=NOW + timedelta(days=1))
    assert work_repo.open_tasks(db, company.id, now=NOW) == []
    assert [t.id for t in work_repo.open_tasks(db, company.id, now=NOW + timedelta(days=2))] == [tid]
    work_repo.complete_task(db, company.id, tid, at=NOW)
    assert work_repo.open_tasks(db, company.id, now=NOW + timedelta(days=2)) == []


def test_open_wait_schedules_timer_and_received_cancels_it(db: Session, company: Company) -> None:
    case_id, party = _case(db, company)
    wid = work_repo.open_wait(db, company.id, case_id, party, about="Offerte lekkage", expected_by=NOW)
    assert work_repo.open_wait(db, company.id, case_id, party, about="again", expected_by=NOW) == wid
    timer = db.scalar(select(Timer).where(Timer.company_id == company.id, Timer.kind == work_repo.WAIT_DUE))
    assert timer is not None
    assert (timer.due_at, timer.payload) == (NOW, {"wait_id": str(wid)})
    assert work_repo.mark_received(db, company.id, case_id, party) == [wid]
    db.refresh(timer)
    assert timer.status is TimerStatus.cancelled
    assert work_repo.get_wait(db, company.id, wid).status is WaitStatus.received


def test_record_chase_reschedules(db: Session, company: Company) -> None:
    case_id, party = _case(db, company)
    wid = work_repo.open_wait(db, company.id, case_id, party, about="Offerte", expected_by=NOW)
    work_repo.record_chase(db, company.id, wid, at=NOW, next_due=NOW + timedelta(days=3))
    wait = work_repo.get_wait(db, company.id, wid)
    assert (wait.chase_count, wait.last_chased_at, wait.expected_by, wait.status) == (
        1, NOW, NOW + timedelta(days=3), WaitStatus.waiting
    )  # fmt: skip
    keys = set(db.scalars(select(Timer.dedupe_key).where(Timer.company_id == company.id)).all())
    assert keys == {f"wait:{wid}:0", f"wait:{wid}:1"}
    work_repo.escalate_wait(db, company.id, wid)
    assert work_repo.get_wait(db, company.id, wid).status is WaitStatus.escalated
    assert work_repo.overdue_waits(db, company.id, NOW + timedelta(days=10)) == []
    assert work_repo.get_wait(db, company.id, wid).status is not TaskStatus.open
