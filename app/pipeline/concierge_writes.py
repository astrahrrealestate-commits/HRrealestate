"""Write intents of the concierge plan.

Reversible owner-side changes (tasks, pause) run directly and are logged. `draft_reply` and `chase_now` only create
proposals through the existing propose/follow-up stages: the result points at the approval, and only the owner's
approve click can lead to a send. Nothing here takes a recipient from the plan.
"""

from datetime import timedelta
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.contracts import Direction, PlanStep
from app.core.errors import NotFoundError
from app.db.enums import TaskStatus, WaitStatus
from app.db.models import CaseLink, MessageRow, TaskRow, WaitRow
from app.pipeline import followups, propose, read_work, timers, work_repo
from app.pipeline.concierge_base import NEED_DETAIL, NOT_FOUND, Ctx, StepResult, failed, log_change, task_ref
from app.pipeline.concierge_sanitize import sanitize
from app.pipeline.owner_commands import parse_duration

TITLE_MAX = 200
NOTHING_TO_REPLY = "nothing to reply to on that case"
NOTHING_TO_CHASE = "We are not waiting on anyone for that case, so there is nothing to chase."
NO_PROPOSAL = "No proposal was created (proposals may be paused, or nothing is due)."
RESUME_IN_DASHBOARD = "Use Resume in the dashboard to re-run approved items."
READY = "Ready for your approval in Approvals. Nothing is sent until you approve it."


def _task(session: Session, ctx: Ctx, step: PlanStep) -> TaskRow | None:
    ref = task_ref(step.task_ref)
    if ref is None:
        return None
    try:
        task_id = work_repo.resolve_task(session, ctx.company_id, ref)
    except NotFoundError:
        return None
    return session.scalar(select(TaskRow).where(TaskRow.company_id == ctx.company_id, TaskRow.id == task_id))


def _local(ctx: Ctx, session: Session) -> ZoneInfo:
    return ZoneInfo(read_work.get_company(session, ctx.company_id).timezone)


def task_done(ctx: Ctx, step: PlanStep) -> StepResult:
    with Session(ctx.engine) as session, session.begin():
        task = _task(session, ctx, step)
        if task is None:
            return failed(step, NOT_FOUND)
        work_repo.complete_task(session, ctx.company_id, task.id, at=ctx.now)
        title, task_id = task.title, task.id
    log_change(ctx, step)
    return StepResult(step.intent, True, f"Done: {title}", {"task_id": str(task_id)}, "tasks")


def task_snooze(ctx: Ctx, step: PlanStep) -> StepResult:
    try:
        duration: timedelta = parse_duration(sanitize(step.text or ""))
    except ValueError as exc:
        return failed(step, str(exc))  # the message quotes at most 12 characters of the sanitised text
    until = ctx.now + duration
    with Session(ctx.engine) as session, session.begin():
        task = _task(session, ctx, step)
        if task is None:
            return failed(step, NOT_FOUND)
        work_repo.snooze_task(session, ctx.company_id, task.id, until=until)
        title, task_id, tz = task.title, task.id, _local(ctx, session)
    log_change(ctx, step)
    data = {"task_id": str(task_id), "until": until.isoformat()}
    return StepResult(step.intent, True, f"Snoozed: {title} until {until.astimezone(tz):%a %d %b %H:%M}", data, "tasks")


def create_task(ctx: Ctx, step: PlanStep) -> StepResult:
    """An open owner task with the same title is reused, so a retried plan never adds the task twice."""
    title = sanitize(step.text or "")[:TITLE_MAX].strip()
    if not title:
        return failed(step, NEED_DETAIL)
    with Session(ctx.engine) as session, session.begin():
        task_id = session.scalar(
            select(TaskRow.id).where(
                TaskRow.company_id == ctx.company_id,
                TaskRow.source == "owner",
                TaskRow.title == title,
                TaskRow.status.in_([TaskStatus.open, TaskStatus.snoozed]),
            )
        ) or work_repo.create_task(session, ctx.company_id, title=title, assignee="owner", source="owner")
    log_change(ctx, step)
    data = {"task_id": str(task_id), "ref": work_repo.short_ref(task_id)}
    return StepResult(step.intent, True, f"Task added: {title} #{work_repo.short_ref(task_id)}", data, "tasks")


def pause(ctx: Ctx, step: PlanStep) -> StepResult:
    with Session(ctx.engine) as session, session.begin():
        read_work.get_company(session, ctx.company_id).paused = True
    log_change(ctx, step)
    return StepResult(step.intent, True, "Paused: no new proposals until you resume.", {"paused": True}, None)


def resume(ctx: Ctx, step: PlanStep) -> StepResult:
    """Resuming must re-run approved actions, which only the dashboard's resume endpoint does; no change here."""
    return StepResult(step.intent, False, RESUME_IN_DASHBOARD, None, None)


def _latest_inbound(session: Session, ctx: Ctx, case_id: UUID) -> UUID | None:
    return session.scalar(
        select(MessageRow.id)
        .join(CaseLink, CaseLink.message_id == MessageRow.id)
        .where(
            CaseLink.company_id == ctx.company_id,
            CaseLink.case_id == case_id,
            MessageRow.company_id == ctx.company_id,
            MessageRow.direction == Direction.inbound,
        )
        .order_by(MessageRow.sent_at.desc(), MessageRow.id.desc())
        .limit(1)
    )


def draft_reply(ctx: Ctx, step: PlanStep) -> StepResult:
    """The propose stage works per message: the case's latest inbound message is the one answered. The proposal is
    replay-safe there (one set of actions per message), and the recipient is resolved from the DB at send time."""
    if step.case_id is None:
        return failed(step, NEED_DETAIL)
    with Session(ctx.engine) as session:
        message_id = _latest_inbound(session, ctx, step.case_id)
    if message_id is None:
        return failed(step, NOTHING_TO_REPLY)
    result = propose.propose_for_message(ctx.engine, ctx.settings, message_id)
    log_change(ctx, step)
    if not result.approval_ids:
        return failed(step, NO_PROPOSAL)
    data = {"approval_ids": [str(a) for a in result.approval_ids], "case_id": str(step.case_id)}
    return StepResult(step.intent, True, f"Reply drafted. {READY}", data, "approvals")


def _open_wait(session: Session, ctx: Ctx, case_id: UUID) -> WaitRow | None:
    return session.scalar(
        select(WaitRow)
        .where(WaitRow.company_id == ctx.company_id, WaitRow.case_id == case_id, WaitRow.status == WaitStatus.waiting)
        .order_by(WaitRow.expected_by, WaitRow.id)
        .limit(1)
    )


def _chase_step(wait: WaitRow, ctx: Ctx) -> int:
    """A retried plan (same `now`) finds the chase it already recorded and replays that step instead of chasing
    again: the follow-up stage then hands back the card it created."""
    replay = wait.last_chased_at is not None and wait.last_chased_at >= ctx.now
    return wait.chase_count - 1 if replay else wait.chase_count


def _retire_timer(ctx: Ctx, wait_id: UUID, step_no: int) -> None:
    """The step's pending `wait.due` timer would only re-show the card; cancel it once the wait moved on."""
    with Session(ctx.engine) as session, session.begin():
        wait = work_repo.get_wait(session, ctx.company_id, wait_id)
        if wait.chase_count > step_no or wait.status is not WaitStatus.waiting:
            timers.cancel(session, ctx.company_id, f"wait:{wait_id}:{step_no}")  # key format: work_repo._schedule_due


def chase_now(ctx: Ctx, step: PlanStep) -> StepResult:
    if step.case_id is None:
        return failed(step, NEED_DETAIL)
    with Session(ctx.engine) as session:
        wait = _open_wait(session, ctx, step.case_id)
        if wait is None:
            return failed(step, NOTHING_TO_CHASE)
        wait_id, step_no = wait.id, _chase_step(wait, ctx)
    approval_id = followups.handle_wait_due(
        ctx.engine, ctx.settings, ctx.company_id, wait_id, step=step_no, now=ctx.now, force=True
    )
    _retire_timer(ctx, wait_id, step_no)
    log_change(ctx, step)
    if approval_id is None:
        return failed(step, NO_PROPOSAL)
    data = {"approval_ids": [str(approval_id)], "case_id": str(step.case_id), "wait_id": str(wait_id)}
    return StepResult(step.intent, True, f"Follow-up prepared. {READY}", data, "approvals")
