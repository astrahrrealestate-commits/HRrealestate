"""Concierge intents that could lead to a tenant message: `draft_reply` and `chase_now`.

They only create proposals through the existing propose/follow-up stages. The result points at the approval, and only
the owner's approve click can lead to a send. Nothing here takes a recipient from the plan; the sender resolves it from
the DB at send time.
"""

from collections.abc import Sequence
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.contracts import ActionType, Direction, PlanStep
from app.db.enums import ActionStatus, ApprovalStatus, WaitStatus
from app.db.models import ActionRow, Approval, CaseLink, MessageRow, UnderstandingRow, WaitRow
from app.pipeline import followups, propose, timers, work_repo
from app.pipeline.concierge_base import NEED_DETAIL, Ctx, StepResult, failed, log_change

READY = "Nothing is sent until you approve it in Approvals."
NOTHING_TO_REPLY = "nothing to reply to on that case"
NOT_UNDERSTOOD = "The latest message on that case is still being processed. Try again in a minute."
NO_REPLY_NEEDED = "The latest message on that case does not need a reply, so I did not draft one."
ALREADY_WAITING = f"A reply for that case is already waiting for your approval. {READY}"
ALREADY_DECIDED = "The latest message on that case was already handled (its proposal was decided)."
HELD = "The draft was held for your review (paused or flagged). Look at the case before replying."
PROPOSER_FAILED = "I could not draft a reply. A notice is waiting in Approvals so you can handle it yourself."
DRAFTED = f"Reply drafted. {READY}"
NOTHING_TO_CHASE = "We are not waiting on anyone for that case, so there is nothing to chase."
CHASER_WAITING = f"A follow-up for that case is already waiting for your approval. {READY}"
CHASED = f"Follow-up prepared. {READY}"
NO_CHASER = "No follow-up was created (proposals may be paused, or this step was already handled)."


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


def _message_actions(session: Session, ctx: Ctx, message_id: UUID) -> list[ActionRow]:
    q = select(ActionRow).where(ActionRow.company_id == ctx.company_id, ActionRow.context_ref.contains([message_id]))
    return list(session.scalars(q))


def _understood(session: Session, ctx: Ctx, message_id: UUID) -> bool:
    q = select(UnderstandingRow.id).where(
        UnderstandingRow.company_id == ctx.company_id, UnderstandingRow.message_id == message_id
    )
    return session.scalar(q) is not None


def _no_approval_text(session: Session, ctx: Ctx, message_id: UUID, actions: Sequence[ActionRow]) -> str:
    if not actions:
        return NO_REPLY_NEEDED if _understood(session, ctx, message_id) else NOT_UNDERSTOOD
    if any(a.status in (ActionStatus.paused, ActionStatus.exception) for a in actions):
        return HELD
    return ALREADY_DECIDED


def _pending_ids(session: Session, ctx: Ctx, actions: Sequence[ActionRow]) -> list[UUID]:
    if not actions:
        return []
    q = select(Approval.id).where(
        Approval.company_id == ctx.company_id,
        Approval.action_id.in_([a.id for a in actions]),
        Approval.status == ApprovalStatus.pending,
    )
    return list(session.scalars(q))


def draft_reply(ctx: Ctx, step: PlanStep) -> StepResult:
    """The propose stage works per message: the case's latest inbound message is the one answered (replay-safe there,
    one set of actions per message). The summary says honestly what happened."""
    if step.case_id is None:
        return failed(step, NEED_DETAIL)
    with Session(ctx.engine) as session:
        message_id = _latest_inbound(session, ctx, step.case_id)
        already = bool(message_id and _pending_ids(session, ctx, _message_actions(session, ctx, message_id)))
    if message_id is None:
        return failed(step, NOTHING_TO_REPLY)
    result = propose.propose_for_message(ctx.engine, ctx.settings, message_id)
    log_change(ctx, step)
    data = {"approval_ids": [str(a) for a in result.approval_ids], "case_id": str(step.case_id)}
    with Session(ctx.engine) as session:
        actions = _message_actions(session, ctx, message_id)
        if not result.approval_ids:
            return failed(step, _no_approval_text(session, ctx, message_id, actions))
    if any(a.type is ActionType.notify_owner and a.rationale == propose.FALLBACK_RATIONALE for a in actions):
        return StepResult(step.intent, False, PROPOSER_FAILED, data, "approvals")
    return StepResult(step.intent, True, ALREADY_WAITING if already else DRAFTED, data, "approvals")


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
