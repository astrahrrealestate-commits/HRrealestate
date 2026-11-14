"""Concierge `chase_now`: a follow-up for the case's oldest open wait through the follow-up stage.

It only creates a proposal; the result points at the approval and only the owner's approve click can lead to a send.
Nothing here takes a recipient from the plan; the sender resolves it from the DB at send time.
"""

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.contracts import PlanStep
from app.db.enums import WaitStatus
from app.db.models import WaitRow
from app.pipeline import followups, timers, work_repo
from app.pipeline.concierge_base import NEED_DETAIL, Ctx, StepResult, failed, log_change
from app.pipeline.draft_guidance import READY

NOTHING_TO_CHASE = "We are not waiting on anyone for that case, so there is nothing to chase."
CHASER_WAITING = f"A follow-up for that case is already waiting for your approval. {READY}"
CHASED = f"Follow-up prepared. {READY}"
NO_CHASER = "No follow-up was created (proposals may be paused, or this step was already handled)."


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
        wait_id, step_no = wait.id, _chase_step(wait, ctx)
    if pending is not None:
        return _chased(step, pending, wait_id, CHASER_WAITING)
    approval_id = followups.handle_wait_due(
        ctx.engine, ctx.settings, ctx.company_id, wait_id, step=step_no, now=ctx.now, force=True
    )
    _retire_timer(ctx, wait_id, step_no)
    log_change(ctx, step)
    if approval_id is None:
        return failed(step, NO_CHASER)
    return _chased(step, approval_id, wait_id, CHASED)
