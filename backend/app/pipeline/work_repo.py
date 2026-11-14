"""Owner tasks (#6) and waiting-for items (#5). Created by code only, never by the model.

Each open wait has one pending `wait.due` timer per chase step (`wait:{id}:{chase_count}`), so a replayed step never
schedules twice. Every function takes `company_id` and flushes; the caller commits.
"""

from datetime import datetime
from uuid import UUID

from sqlalchemy import String, cast, or_, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.core.errors import NotFoundError
from app.db.enums import TaskPriority, TaskStatus, WaitStatus
from app.db.models import TaskRow, WaitRow
from app.pipeline import timers

WAIT_DUE = "wait.due"
SHORT_REF_LEN = 6


def short_ref(task_id: UUID) -> str:
    """What Harjot types in `done <ref>`: the random tail of the UUIDv7 (the head is a timestamp)."""
    return task_id.hex[-SHORT_REF_LEN:]


def create_task(
    session: Session,
    company_id: UUID,
    *,
    title: str,
    assignee: str,
    source: str,
    case_id: UUID | None = None,
    action_id: UUID | None = None,
    due_at: datetime | None = None,
    priority: TaskPriority = TaskPriority.p2,
) -> UUID:
    values = {
        "company_id": company_id,
        "case_id": case_id,
        "action_id": action_id,
        "title": title[:200],
        "assignee": assignee,
        "source": source,
        "due_at": due_at,
        "priority": priority,
    }
    if action_id is None:
        task = TaskRow(**values)
        session.add(task)
        session.flush()
        return task.id
    session.execute(
        insert(TaskRow)
        .values(**values)
        .on_conflict_do_nothing(index_elements=["action_id", "source"], index_where=TaskRow.action_id.is_not(None))
    )
    return session.execute(
        select(TaskRow.id).where(
            TaskRow.company_id == company_id, TaskRow.action_id == action_id, TaskRow.source == source
        )
    ).scalar_one()


def close_action_tasks(session: Session, company_id: UUID, action_id: UUID) -> int:
    result = session.execute(
        update(TaskRow)
        .where(
            TaskRow.company_id == company_id,
            TaskRow.action_id == action_id,
            TaskRow.status.in_([TaskStatus.open, TaskStatus.snoozed]),
        )
        .values(status=TaskStatus.done)
    )
    return int(result.rowcount)  # type: ignore[attr-defined]  # CursorResult of an UPDATE


def open_tasks(session: Session, company_id: UUID, now: datetime | None = None) -> list[TaskRow]:
    """Open tasks plus snoozed ones whose snooze has ended (when `now` is given), most urgent first."""
    visible = TaskRow.status == TaskStatus.open
    if now is not None:
        visible = or_(visible, (TaskRow.status == TaskStatus.snoozed) & (TaskRow.snoozed_until <= now))
    return list(
        session.scalars(
            select(TaskRow)
            .where(TaskRow.company_id == company_id, visible)
            .order_by(TaskRow.priority, TaskRow.due_at.nulls_last(), TaskRow.created_at)
        ).all()
    )


def resolve_task(session: Session, company_id: UUID, ref: str) -> UUID:
    matches = session.scalars(
        select(TaskRow.id).where(
            TaskRow.company_id == company_id,
            TaskRow.status.in_([TaskStatus.open, TaskStatus.snoozed]),
            cast(TaskRow.id, String).like(f"%{ref.strip().lower()}"),
        )
    ).all()
    if len(ref.strip()) < SHORT_REF_LEN or len(matches) != 1:
        raise NotFoundError(f"no single open task matches {ref[:12]!r}")
    return matches[0]


def _task(session: Session, company_id: UUID, task_id: UUID) -> TaskRow:
    task = session.scalar(select(TaskRow).where(TaskRow.id == task_id, TaskRow.company_id == company_id))
    if task is None:
        raise NotFoundError(f"task {task_id} not found")
    return task


def complete_task(session: Session, company_id: UUID, task_id: UUID, *, at: datetime) -> None:
    task = _task(session, company_id, task_id)
    task.status, task.done_at = TaskStatus.done, at
    session.flush()


def snooze_task(session: Session, company_id: UUID, task_id: UUID, *, until: datetime) -> None:
    task = _task(session, company_id, task_id)
    task.status, task.snoozed_until = TaskStatus.snoozed, until
    session.flush()


def get_wait(session: Session, company_id: UUID, wait_id: UUID) -> WaitRow:
    wait = session.scalar(select(WaitRow).where(WaitRow.id == wait_id, WaitRow.company_id == company_id))
    if wait is None:
        raise NotFoundError(f"wait {wait_id} not found")
    return wait


def _schedule_due(session: Session, wait: WaitRow) -> None:
    timers.schedule(
        session,
        wait.company_id,
        WAIT_DUE,
        wait.expected_by,
        {"wait_id": str(wait.id), "step": wait.chase_count},
        dedupe_key=f"wait:{wait.id}:{wait.chase_count}",
    )


def open_wait(
    session: Session,
    company_id: UUID,
    case_id: UUID,
    party_person_id: UUID | None,
    *,
    about: str,
    expected_by: datetime,
    source_action_id: UUID | None = None,
) -> UUID:
    """One open wait per (case, party): an existing one is returned unchanged."""
    session.execute(
        insert(WaitRow)
        .values(
            company_id=company_id,
            case_id=case_id,
            party_person_id=party_person_id,
            about=about[:300],
            expected_by=expected_by,
            source_action_id=source_action_id,
        )
        .on_conflict_do_nothing(
            index_elements=["case_id", "party_person_id"], index_where=WaitRow.status == WaitStatus.waiting
        )
    )
    wait = session.execute(
        select(WaitRow).where(
            WaitRow.company_id == company_id,
            WaitRow.case_id == case_id,
            WaitRow.party_person_id == party_person_id,
            WaitRow.status == WaitStatus.waiting,
        )
    ).scalar_one()
    _schedule_due(session, wait)
    return wait.id


def mark_received(session: Session, company_id: UUID, case_id: UUID, party_person_id: UUID) -> list[UUID]:
    """The party answered on this case: close its open waits and cancel their pending timers."""
    waits = session.scalars(
        select(WaitRow).where(
            WaitRow.company_id == company_id,
            WaitRow.case_id == case_id,
            WaitRow.party_person_id == party_person_id,
            WaitRow.status == WaitStatus.waiting,
        )
    ).all()
    for wait in waits:
        wait.status = WaitStatus.received
        timers.cancel(session, company_id, f"wait:{wait.id}:{wait.chase_count}")
    session.flush()
    return [w.id for w in waits]


def record_chase(session: Session, company_id: UUID, wait_id: UUID, *, at: datetime, next_due: datetime) -> None:
    wait = get_wait(session, company_id, wait_id)
    wait.chase_count, wait.last_chased_at, wait.expected_by = wait.chase_count + 1, at, next_due
    session.flush()
    _schedule_due(session, wait)


def escalate_wait(session: Session, company_id: UUID, wait_id: UUID) -> None:
    wait = get_wait(session, company_id, wait_id)
    wait.status = WaitStatus.escalated
    session.flush()


def overdue_waits(session: Session, company_id: UUID, now: datetime) -> list[WaitRow]:
    return list(
        session.scalars(
            select(WaitRow)
            .where(WaitRow.company_id == company_id, WaitRow.status == WaitStatus.waiting, WaitRow.expected_by < now)
            .order_by(WaitRow.expected_by)
        ).all()
    )
