"""Approve a maintenance dispatch: decide the case's pending approvals through the canonical approval path.

The API never sends (CLAUDE.md invariant 5): each approved action is executed by `app/sender/` through the
`exec:{action_id}:{draft_version}` workflow, which re-checks approval, pause, `outbound_mode` and the recipient.
"""

from datetime import datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.contracts import ActionType, ButtonChoice
from app.core.logging import get_logger
from app.db.enums import ApprovalStatus
from app.db.models import ActionRow, Approval, Case
from app.pipeline import approvals, dashboard_decisions
from app.pipeline.local_actions import LOCAL_TYPES

log = get_logger(__name__)


def _pending(session: Session, case: Case) -> list[tuple[ActionRow, Approval]]:
    rows = session.execute(
        select(ActionRow, Approval)
        .join(Approval, Approval.action_id == ActionRow.id)
        .where(
            ActionRow.company_id == case.company_id,
            ActionRow.case_id == case.id,
            Approval.company_id == case.company_id,
            Approval.status == ApprovalStatus.pending,
        )
        .order_by(Approval.created_at)
    ).all()
    return [(row[0], row[1]) for row in rows]


def _edited_text(action: ActionRow, contractor_text: str | None, tenant_text: str | None) -> str | None:
    if action.type is ActionType.request_contractor:
        return contractor_text
    return tenant_text if action.type is ActionType.reply_draft else None


def approve_case(
    session: Session,
    case: Case,
    *,
    dispatch_contractor: bool,
    notify_tenant: bool,
    texts: tuple[str | None, str | None],
    at: datetime,
) -> list[tuple[approvals.Decision, bool]]:
    """Decide (d1) every pending approval of the case; the contractor request only when dispatching, the tenant
    reply only when notifying. Owner-edited text becomes a new draft version first. Returns (decision, local).
    Raises dashboard_decisions.SuspiciousNeedsConfirmError / NotEditableError for the caller to answer 409."""
    skip = {ActionType.request_contractor} if not dispatch_contractor else set()
    if not notify_tenant:
        skip.add(ActionType.reply_draft)
    decided: list[tuple[approvals.Decision, bool]] = []
    for action, approval in _pending(session, case):
        if action.type in skip:
            continue
        approval_id: UUID = approval.id
        text = _edited_text(action, *texts)
        if text and text.strip():
            approval_id = dashboard_decisions.edit_approval(
                session, case.company_id, approval_id, text, at=at
            ).approval_id
        decision = dashboard_decisions.decide_approval(
            session, case.company_id, approval_id, ButtonChoice.d1, at=at, confirm_suspicious=False
        )
        decided.append((decision, action.type in LOCAL_TYPES))
    log.info("maintenance.approvals_decided", case_id=str(case.id), count=len(decided))
    return decided
