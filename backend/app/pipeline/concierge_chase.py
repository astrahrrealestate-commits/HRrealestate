"""Concierge `chase_now`: a follow-up for the case's oldest open wait through the follow-up stage.

It only creates a proposal; the result points at the approval and only the owner's approve click can lead to a send.
Nothing here takes a recipient from the plan; the sender resolves it from the DB at send time.
"""

import re
from datetime import date, datetime, timedelta
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.contracts import CaseState, PlanStep
from app.db.enums import WaitStatus
from app.db.models import WaitRow
from app.pipeline import case_repo, chasing, followups, read_work, timers, work_repo
from app.pipeline.concierge_base import NEED_DETAIL, Ctx, StepResult, failed, log_change
from app.pipeline.concierge_sanitize import sanitize
from app.pipeline.draft_guidance import READY
from app.pipeline.owner_commands import parse_duration

NOTHING_TO_CHASE = "We are not waiting on anyone for that case, so there is nothing to chase."
CHASER_WAITING = f"A follow-up for that case is already waiting for your approval. {READY}"
CHASED = f"Follow-up prepared. {READY}"
NO_CHASER = "No follow-up was created (proposals may be paused, or this step was already handled)."

_WEEKDAYS = {
    "monday": 0, "maandag": 0,
    "tuesday": 1, "dinsdag": 1,
    "wednesday": 2, "woensdag": 2,
    "thursday": 3, "donderdag": 3,
    "friday": 4, "vrijdag": 4,
    "saturday": 5, "zaterdag": 5,
    "sunday": 6, "zondag": 6,
}
_ISO_DATE_RE = re.compile(r"\b(\d{4}-\d{2}-\d{2})\b")
_MONTH_DAY_RE = re.compile(r"\b(\d{1,2})(?:st|nd|rd|th|e)?\b")


def _parse_target_due(raw: str, now: datetime, tz: str) -> datetime | None:
    clean = sanitize(raw or "").strip().lower()
    if not clean:
        return None
    zone = ZoneInfo(tz)
    today = now.astimezone(zone).date()

    m_iso = _ISO_DATE_RE.search(clean)
    if m_iso:
        try:
            target = date.fromisoformat(m_iso.group(1))
            return chasing.next_morning_after(max(target, today), tz)
        except ValueError:
            pass

    if "tomorrow" in clean or "morgen" in clean:
        return chasing.next_morning_after(today + timedelta(days=1), tz)

    for word, wd in _WEEKDAYS.items():
        if re.search(rf"\b{word}\b", clean):
            delta = (wd - today.weekday()) % 7
            if delta == 0:
                delta = 7
            return chasing.next_morning_after(today + timedelta(days=delta), tz)

    try:
        dur = parse_duration(clean)
        target = (now + dur).astimezone(zone).date()
        return chasing.next_morning_after(max(target, today), tz)
    except ValueError:
        pass

    m_day = _MONTH_DAY_RE.search(clean)
    if m_day:
        day_num = int(m_day.group(1))
        if 1 <= day_num <= 31:
            for month_offset in (0, 1):
                y = today.year + (today.month - 1 + month_offset) // 12
                m = (today.month - 1 + month_offset) % 12 + 1
                try:
                    cand = date(y, m, day_num)
                except ValueError:
                    continue
                if cand >= today:
                    return chasing.next_morning_after(cand, tz)
    return None


def _open_wait(session: Session, ctx: Ctx, case_id: UUID) -> WaitRow | None:
    return work_repo.active_case_wait(session, ctx.company_id, case_id)


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


def _chased(step: PlanStep, approval_id: UUID, wait_id: UUID, summary: str) -> StepResult:
    data = {"approval_ids": [str(approval_id)], "case_id": str(step.case_id), "wait_id": str(wait_id)}
    return StepResult(step.intent, True, summary, data, "approvals")


def chase_now(ctx: Ctx, step: PlanStep) -> StepResult:
    """A chaser still waiting for the owner is returned as is: asking again never moves the ladder."""
    if step.case_id is None:
        return failed(step, NEED_DETAIL)
    with Session(ctx.engine) as session:
        wait = _open_wait(session, ctx, step.case_id)
        if wait is None:
            return failed(step, NOTHING_TO_CHASE)
        pending = followups.pending_step_approval(session, wait)
        wait_id, step_no, is_escalated = wait.id, _chase_step(wait, ctx), wait.status is WaitStatus.escalated
    if pending is not None:
        return _chased(step, pending, wait_id, CHASER_WAITING)
    if is_escalated:
        approval_id = followups.ensure_case_chaser_draft(
            ctx.engine, ctx.settings, ctx.company_id, step.case_id, now=ctx.now
        )
    else:
        approval_id = followups.handle_wait_due(
            ctx.engine, ctx.settings, ctx.company_id, wait_id, step=step_no, now=ctx.now, force=True
        )
        _retire_timer(ctx, wait_id, step_no)
    log_change(ctx, step)
    if approval_id is None:
        return failed(step, NO_CHASER)
    return _chased(step, approval_id, wait_id, CHASED)


def reschedule_wait(ctx: Ctx, step: PlanStep) -> StepResult:
    """Move a case's active wait (or open one) to a promised date / duration so overdue flips next morning 09:00."""
    if step.case_id is None or not (step.text or "").strip():
        return failed(step, NEED_DETAIL)
    with Session(ctx.engine) as session, session.begin():
        tz = read_work.get_company(session, ctx.company_id).timezone
        due = _parse_target_due(step.text or "", ctx.now, tz)
        if due is None:
            return failed(step, "Give a date (e.g. Tuesday, 2026-12-01, or 3d) to move this commitment to.")
        case = case_repo.get_case(session, ctx.company_id, step.case_id)
        wait = work_repo.active_case_wait(session, ctx.company_id, step.case_id)
        if wait is not None:
            work_repo.reschedule_wait(session, ctx.company_id, wait.id, expected_by=due)
            wait_id = wait.id
        else:
            wait_id = work_repo.open_wait(
                session,
                ctx.company_id,
                step.case_id,
                case.primary_person_id,
                about="Awaiting promised update",
                expected_by=due,
            )
            if case.state is CaseState.open:
                case_repo.transition(session, ctx.company_id, case.id, CaseState.waiting_on_third_party, actor="owner")
        local_due = due.astimezone(ZoneInfo(tz))
    log_change(ctx, step)
    return StepResult(
        step.intent,
        True,
        f"Moved commitment deadline: overdue check at {local_due:%a %d %b %H:%M}.",
        {"case_id": str(step.case_id), "wait_id": str(wait_id), "expected_by": due.isoformat()},
        "waiting",
    )


def mark_received(ctx: Ctx, step: PlanStep) -> StepResult:
    """Confirm the awaited item arrived or an owner commitment was fulfilled."""
    if step.case_id is None:
        return failed(step, NEED_DETAIL)
    with Session(ctx.engine) as session, session.begin():
        case = case_repo.get_case(session, ctx.company_id, step.case_id)
        waits_closed = work_repo.resolve_case_waits(session, ctx.company_id, step.case_id)
        tasks_closed = (
            work_repo.close_case_tasks(session, ctx.company_id, step.case_id, source="promise")
            + work_repo.close_case_tasks(session, ctx.company_id, step.case_id, source="reminder")
        )
        if case.state in (CaseState.waiting_on_third_party, CaseState.waiting_on_owner):
            case_repo.transition(session, ctx.company_id, case.id, CaseState.open, actor="owner")
    log_change(ctx, step)
    if waits_closed + tasks_closed == 0:
        return StepResult(
            step.intent, True, "No active waits or open promises on that case.", {"case_id": str(step.case_id)}, "waiting"
        )
    return StepResult(
        step.intent,
        True,
        "Marked commitment complete and cleared pending chasers.",
        {"case_id": str(step.case_id), "waits_closed": waits_closed, "tasks_closed": tasks_closed},
        "waiting",
    )
