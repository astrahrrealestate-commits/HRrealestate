"""The inbox's 1-click approve: resolve the target, decide it through the canonical approval path, enqueue the send.

Sending is never done here (CLAUDE.md invariant 5): an approved reply is executed by `app/sender/` through the
`exec:{action_id}:{draft_version}` workflow, which re-checks approval, draft version, pause, `outbound_mode`, the
recipient and the idempotency key.
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.contracts import ActionType, ButtonChoice, CaseState, Channel
from app.core.logging import get_logger
from app.db.enums import ActionStatus, ApprovalStatus, CaseEventKind
from app.db.models import ActionRow, Approval, Case, CaseEvent, Company, MessageRow
from app.pipeline import approvals, dashboard_decisions
from app.pipeline.local_actions import LOCAL_TYPES

log = get_logger(__name__)

CHOICES = {
    "d1": ButtonChoice.d1,
    "d2": ButtonChoice.d2,
    "d3": ButtonChoice.d3,
    "ok": ButtonChoice.ok,
    "edit": ButtonChoice.d1,  # "edit" without text approves the first draft; with text it is revised first
    "reject": ButtonChoice.rej,
}


@dataclass(frozen=True)
class Target:
    approval: Approval | None
    action: ActionRow | None
    case: Case | None


@dataclass(frozen=True)
class Outcome:
    decision: approvals.Decision | None
    local: bool


def _reply_action(session: Session, case_id: UUID) -> ActionRow | None:
    return session.scalars(
        select(ActionRow)
        .where(ActionRow.case_id == case_id, ActionRow.type == ActionType.reply_draft)
        .order_by(ActionRow.created_at.desc())
    ).first()


def _live_approval(session: Session, action: ActionRow) -> Approval | None:
    """The pending approval of the action's live draft, else its latest approval."""
    rows = session.scalars(
        select(Approval)
        .where(Approval.company_id == action.company_id, Approval.action_id == action.id)
        .order_by(Approval.created_at.desc())
    ).all()
    return next((a for a in rows if a.status is ApprovalStatus.pending), rows[0] if rows else None)


def _from_case(session: Session, case: Case | None) -> Target:
    action = _reply_action(session, case.id) if case else None
    return Target(_live_approval(session, action) if action else None, action, case)


def resolve(session: Session, ref: str) -> Target:
    """An approval id, a case id (`case-…`), an action id (`act-…`), or else the latest unresolved case."""
    try:
        target_id = UUID(ref.replace("case-", "").replace("act-", ""))
    except ValueError:
        latest = session.scalars(
            select(Case).where(Case.state != CaseState.resolved).order_by(Case.opened_at.desc())
        ).first()
        return _from_case(session, latest)
    approval = session.get(Approval, target_id)
    if approval is not None:
        action = session.get(ActionRow, approval.action_id)
        return Target(approval, action, session.get(Case, action.case_id) if action else None)
    case = session.get(Case, target_id)
    if case is not None:
        return _from_case(session, case)
    action = session.get(ActionRow, target_id)
    if action is None:
        return Target(None, None, None)
    return Target(_live_approval(session, action), action, session.get(Case, action.case_id))


def decide(session: Session, target: Target, choice: ButtonChoice, text: str | None, at: datetime) -> Outcome:
    """Edit first when text was given (a new draft version and approval), then decide the live approval.
    Raises dashboard_decisions.SuspiciousNeedsConfirmError / NotEditableError for the caller to answer 409."""
    approval, action = target.approval, target.action
    if approval is None or action is None:
        return Outcome(None, False)
    approval_id = approval.id
    if text and text.strip() and choice is not ButtonChoice.rej:
        approval_id = dashboard_decisions.edit_approval(
            session, approval.company_id, approval_id, text, at=at
        ).approval_id
        choice = ButtonChoice.d1
    decision = dashboard_decisions.decide_approval(
        session, approval.company_id, approval_id, choice, at=at, confirm_suspicious=False
    )
    return Outcome(decision, action.type in LOCAL_TYPES)


def guard(session: Session, target: Target, at: datetime) -> dict[str, Any] | None:
    """Answers that need no decision: a repeated click on a decided approval, or a paused company (the action is
    held; the sender re-checks the pause as well). None means go on and decide."""
    approval, action = target.approval, target.action
    if approval is None or action is None:
        return None
    if approval.status is not ApprovalStatus.pending:
        return {
            "status": "already_decided",
            "approvalId": str(approval.id),
            "decision": approval.status.value,
            "message": f"Approval {approval.id} has already been decided.",
            "executedAt": (approval.decided_at or at).isoformat(),
        }
    company = session.get(Company, action.company_id)
    if company is not None and company.paused:
        action.status = ActionStatus.paused
        return {
            "status": "held",
            "approvalId": str(approval.id),
            "decision": "paused",
            "message": "Company communications are paused. Action held for review.",
            "executedAt": at.isoformat(),
        }
    return None


def remember_quote(session: Session, action: ActionRow, message_ref: str | None) -> None:
    """Display only: the inbox thread shows which tenant message the reply answers (the sender ignores it)."""
    try:
        quoted = session.get(MessageRow, UUID(message_ref)) if message_ref else None
    except ValueError:
        quoted = None
    if quoted is None or quoted.company_id != action.company_id:
        return
    clean_text = (quoted.text or "").strip().strip('"').strip("'")
    payload = dict(action.payload or {})
    payload["reply_to"] = {"id": str(quoted.id), "sender": "Tenant", "text": clean_text[:120]}
    action.payload = payload


def record_dispatch(session: Session, case: Case, action: ActionRow | None, at: datetime) -> None:
    """Case moves to waiting_on_third_party with an audit event and a summary note (once)."""
    from_state = case.state
    case.state = CaseState.waiting_on_third_party
    via_gmail = action is not None and (
        getattr(action, "channel", None) == Channel.gmail or "gmail" in str(action.payload or "").lower()
    )
    note = (
        f"Contractor dispatch approved & dispatched via {'Gmail' if via_gmail else 'WhatsApp'} on "
        f"{at.strftime('%Y-%m-%d %H:%M UTC')}. Waiting on contractor arrival/resolution."
    )
    existing = (case.summary or "").strip()
    if "Contractor dispatch approved" not in existing:
        case.summary = f"{existing}\n\n[Action Taken: {note}]" if existing else f"[Action Taken: {note}]"
        case.summary_version = (case.summary_version or 0) + 1
    session.add(
        CaseEvent(
            company_id=case.company_id,
            case_id=case.id,
            kind=CaseEventKind.state_change,
            from_state=from_state,
            to_state=CaseState.waiting_on_third_party,
            note=note,
            actor="owner",
        )
    )
    log.info("inbox.approval_recorded", case_id=str(case.id))
