"""Reversible write intents of the concierge plan (tasks, standing rules, pause): they run directly and are logged.

Intents that could lead to a tenant message live in `concierge_proposals` and only create proposals.
"""

from datetime import timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.context.memory_items import record_owner_memory
from app.contracts import PlanStep
from app.core.errors import NotFoundError
from app.db.enums import TaskStatus
from app.db.models import TaskRow
from app.pipeline import read_work, work_repo
from app.pipeline.concierge_base import NEED_DETAIL, NOT_FOUND, Ctx, StepResult, failed, log_change, task_ref
from app.pipeline.concierge_sanitize import sanitize
from app.pipeline.owner_commands import parse_duration
from app.pipeline.task_note import task_note

TITLE_MAX = 200
RESUME_IN_DASHBOARD = "Use Resume in the dashboard to re-run approved items."


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
        existing = session.scalar(
            select(TaskRow.id).where(
                TaskRow.company_id == ctx.company_id,
                TaskRow.source == "owner",
                TaskRow.title == title,
                TaskRow.status.in_([TaskStatus.open, TaskStatus.snoozed]),
            )
        )
        task_id = existing or work_repo.create_task(
            session, ctx.company_id, title=title, assignee="owner", source="owner"
        )
    log_change(ctx, step)
    ref = work_repo.short_ref(task_id)
    lead = "Already on your list" if existing else "Task added"
    summary = f"{lead}: {title} #{ref}. {task_note(title, ref)}"
    return StepResult(step.intent, True, summary, {"task_id": str(task_id), "ref": ref}, "tasks")


def remember(ctx: Ctx, step: PlanStep) -> StepResult:
    """A standing rule or preference (concierge/v8), stored like the `remember` command: sanitised, then screened and
    stored by `record_owner_memory`, which refuses rules that bypass approval or send automatically. A restated rule
    is merged into the stored one, so a retried step never adds a second row."""
    text = sanitize(step.text or "").strip()
    if not text:
        return failed(step, NEED_DETAIL)
    with Session(ctx.engine) as session, session.begin():
        item, message = record_owner_memory(session, ctx.company_id, text)
        memory_id = str(item.id) if item is not None else None
    if memory_id is None:
        return failed(step, message)
    log_change(ctx, step)
    return StepResult(step.intent, True, message, {"memory_id": memory_id}, None)


def pause(ctx: Ctx, step: PlanStep) -> StepResult:
    with Session(ctx.engine) as session, session.begin():
        read_work.get_company(session, ctx.company_id).paused = True
    log_change(ctx, step)
    return StepResult(step.intent, True, "Paused: no new proposals until you resume.", {"paused": True}, None)


def resume(ctx: Ctx, step: PlanStep) -> StepResult:
    """Resuming must re-run approved actions, which only the dashboard's resume endpoint does; no change here."""
    return StepResult(step.intent, False, RESUME_IN_DASHBOARD, None, None)
