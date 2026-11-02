"""Concierge `draft_reply` (steerable since amendment 2026-10-22): a reply draft for the case's latest inbound message.

The owner's own message (never the planner's `text`) is sanitised into guidance for the proposer. A message
without a proposal goes through the propose stage; on a turn, a pending reply draft is superseded and a decided one
gets a fresh draft (`redraft`), keyed by turn and step so a retry returns the same revision. The result quotes the
drafts (capped, output-guard flags) and points at the approval: only the owner's approve click can lead to a send.
Nothing here takes a recipient from the plan, the guidance or tenant text; the sender resolves it from the DB.
"""

from collections.abc import Sequence
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.contracts import ActionType, Direction, PlanStep
from app.db.enums import ActionStatus, ApprovalStatus
from app.db.models import ActionRow, Approval, CaseLink, MessageRow, UnderstandingRow
from app.pipeline import propose, redraft
from app.pipeline.concierge_base import NEED_DETAIL, Ctx, StepResult, failed, log_change
from app.pipeline.draft_guidance import (
    READY,
    Guidance,
    draft_views,
    drafted_summary,
    guidance_for,
    redraft_key,
    turn_prefix,
)

NOTHING_TO_REPLY = "nothing to reply to on that case"
NOT_UNDERSTOOD = "The latest message on that case is still being processed. Try again in a minute."
NO_REPLY_NEEDED = "The latest message on that case does not need a reply, so I did not draft one."
ALREADY_WAITING = f"A reply for that case is already waiting for your approval. {READY}"
ALREADY_DECIDED = "The latest message on that case was already handled (its proposal was decided)."
HELD = "The draft was held for your review (paused or flagged). Look at the case before replying."
PROPOSER_FAILED = "I could not draft a reply. A notice is waiting in Approvals so you can handle it yourself."
DRAFTED = f"Reply drafted. {READY}"
REDRAFTED = f"New draft ready: it replaces the one that was waiting for your approval. {READY}"
FRESH_DRAFT = f"The earlier reply on that case was already decided, so I drafted a new one. {READY}"
NOT_REDRAFTED = "I did not create a new draft ({reason}). Nothing was changed."
OTHER_WAITING = (
    "No reply draft is waiting for that case; another proposal for it (such as an escalation) is in Approvals."
)


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


def _reply_of(session: Session, ctx: Ctx, approval_ids: Sequence[UUID]) -> tuple[UUID, int, tuple[str, ...]] | None:
    """The approval, draft version and variants of the reply draft among the approvals (None: no reply among them)."""
    row = session.execute(
        select(Approval.id, ActionRow.draft_version, ActionRow.payload)
        .join(Approval, Approval.action_id == ActionRow.id)
        .where(
            Approval.company_id == ctx.company_id,
            ActionRow.company_id == ctx.company_id,
            Approval.id.in_(approval_ids),
            ActionRow.type == ActionType.reply_draft,
        )
        .limit(1)
    ).first()
    if row is None:
        return None
    return row[0], row[1], tuple(str(v) for v in (row[2] or {}).get("body_variants") or ())


def _source(ctx: Ctx, message_id: UUID) -> str:
    loaded = propose.load_message(ctx.engine, message_id)
    return loaded.source if loaded else ""


def _data(step: PlanStep, approvals: Sequence[UUID], version: int | None, views: list[dict[str, Any]],
          guidance: Guidance, superseded: UUID | None = None) -> dict[str, Any]:  # fmt: skip
    return {
        "approval_ids": [str(a) for a in approvals],
        "case_id": str(step.case_id),
        "draft_version": version,
        "drafts": views,
        "details_removed": guidance.redacted,
        "superseded_approval_id": str(superseded) if superseded else None,
    }


def draft_reply(ctx: Ctx, step: PlanStep) -> StepResult:
    """The case's latest inbound message is the one answered. The summary says honestly what happened and quotes the
    drafts; `data` carries the approval id(s) for approve/edit in the SPA."""
    if step.case_id is None:
        return failed(step, NEED_DETAIL)
    with Session(ctx.engine) as session:
        message_id = _latest_inbound(session, ctx, step.case_id)
    if message_id is None:
        return failed(step, NOTHING_TO_REPLY)
    guidance = guidance_for(ctx.question)  # the owner's own message; the plan's text is model output and ignored
    if ctx.turn_id is not None and (redrafted := _redraft(ctx, step, message_id, guidance)) is not None:
        return redrafted
    return _first_draft(ctx, step, message_id, guidance)


def _first_draft(ctx: Ctx, step: PlanStep, message_id: UUID, guidance: Guidance) -> StepResult:
    """The propose stage (replay-safe per message) with the guidance; on a turn the reply is keyed by turn and step."""
    with Session(ctx.engine) as session:
        before = set(_pending_ids(session, ctx, _message_actions(session, ctx, message_id)))
    key = redraft_key(ctx.turn_id, ctx.step_index) if ctx.turn_id is not None else None
    result = propose.propose_for_message(ctx.engine, ctx.settings, message_id, guidance=guidance.text, key=key)
    log_change(ctx, step)
    with Session(ctx.engine) as session:
        actions = _message_actions(session, ctx, message_id)
        if not result.approval_ids:
            return failed(step, _no_approval_text(session, ctx, message_id, actions))
        reply = _reply_of(session, ctx, result.approval_ids)
    views = draft_views(reply[2], _source(ctx, message_id)) if reply else []
    data = _data(step, result.approval_ids, reply[1] if reply else None, views, guidance)
    if any(a.type is ActionType.notify_owner and a.rationale == propose.FALLBACK_RATIONALE for a in actions):
        return StepResult(step.intent, False, PROPOSER_FAILED, data, "approvals")
    if reply is None:  # only other proposals are live (an escalation; a held reply has no approval)
        held = any(a.status in (ActionStatus.paused, ActionStatus.exception) for a in actions)
        return StepResult(step.intent, False, HELD if held else OTHER_WAITING, data, "approvals")
    headline = ALREADY_WAITING if reply[0] in before else DRAFTED
    summary = drafted_summary(headline, views, details_removed=guidance.redacted)
    return StepResult(step.intent, True, summary, data, "approvals")


def _redraft(ctx: Ctx, step: PlanStep, message_id: UUID, guidance: Guidance) -> StepResult | None:
    """A message that already had a proposal; None when it had none or it is held: the first-draft path reports."""
    turn = ctx.turn_id
    if turn is None:
        return None
    req = redraft.Request(
        ctx.company_id, message_id, guidance.text, turn_prefix(turn), redraft_key(turn, ctx.step_index), ctx.now
    )
    with Session(ctx.engine) as session:
        done = redraft.turn_replay(session, ctx.company_id, req.prefix, message_id)
        state = redraft.message_state(session, ctx.company_id, message_id, ctx.now)
    if done is not None:  # this turn already drafted for the message: the same revision, no model call
        result = redraft.Redraft(done[0], done[1], _source(ctx, message_id))
        return _redrafted(step, result, guidance, REDRAFTED if done[0].draft_version > 1 else DRAFTED)
    if state.kind == "busy":
        return failed(step, NOT_REDRAFTED.format(reason=redraft.BUSY))
    if state.kind == "pending" and state.pending is not None:
        result = redraft.supersede(ctx.engine, ctx.settings, req, state.pending, state.current)
    elif state.kind in ("decided", "no_reply"):
        result = redraft.fresh(ctx.engine, ctx.settings, req, state.current)
    else:
        return None
    log_change(ctx, step)
    headline = REDRAFTED if result.superseded else FRESH_DRAFT if state.kind == "decided" else DRAFTED
    return _redrafted(step, result, guidance, headline)


def _redrafted(step: PlanStep, result: redraft.Redraft, guidance: Guidance, headline: str) -> StepResult:
    views = draft_views(result.variants, result.source)
    if result.revision is None:
        text = NOT_REDRAFTED.format(reason=result.problem or "held for review")
        summary = drafted_summary(text, views, details_removed=guidance.redacted)
        return StepResult(step.intent, False, summary, _data(step, [], None, views, guidance), None)
    rev = result.revision
    data = _data(step, [rev.approval_id], rev.draft_version, views, guidance, result.superseded)
    summary = drafted_summary(headline, views, details_removed=guidance.redacted)
    return StepResult(step.intent, True, summary, data, "approvals")


def show_drafts(ctx: Ctx, step: PlanStep) -> StepResult:
    """Finds pending reply_draft actions for the case so the frontend can render the in-chat draft card."""
    if step.case_id is None:
        return failed(step, NEED_DETAIL)
    with Session(ctx.engine) as session:
        message_id = _latest_inbound(session, ctx, step.case_id)
        if message_id is None:
            actions = list(
                session.scalars(
                    select(ActionRow).where(
                        ActionRow.company_id == ctx.company_id,
                        ActionRow.case_id == step.case_id,
                    )
                )
            )
        else:
            actions = _message_actions(session, ctx, message_id)
            if not actions:
                actions = list(
                    session.scalars(
                        select(ActionRow).where(
                            ActionRow.company_id == ctx.company_id,
                            ActionRow.case_id == step.case_id,
                        )
                    )
                )

        pending_approvals = _pending_ids(session, ctx, actions)
        reply = _reply_of(session, ctx, pending_approvals) if pending_approvals else None

        if reply:
            views = draft_views(reply[2], _source(ctx, message_id)) if message_id else []
            data = {
                "approval_ids": [str(reply[0])],
                "case_id": str(step.case_id),
                "draft_version": reply[1],
                "drafts": views,
            }
            summary = drafted_summary("Here is the drafted reply waiting for your approval.", views, details_removed=False)
            return StepResult(step.intent, True, summary, data, None)

        if pending_approvals:
            data = {
                "approval_ids": [str(a) for a in pending_approvals],
                "case_id": str(step.case_id),
            }
            return StepResult(step.intent, True, "Here is the pending notice for this case.", data, None)

        return failed(step, "No pending draft found for this case. You can ask me to draft one.")
