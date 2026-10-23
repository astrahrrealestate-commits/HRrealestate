"""Supersede a live draft with an owner-requested redraft (Super Agent `draft_reply`, amendment 2026-10-22).

A draft is supersedable while its approval is `pending`, or `edited` (an edit tap) longer ago than the 24 h edit
window (`approvals.EDIT_WINDOW`), after which that edit can no longer be applied: the stale edit is expired here
atomically instead of blocking the case forever. A fresh edit (inside the window) is never superseded: the owner is
writing his own text.

Locks follow `approvals.decide`: the approval, then its action, each `FOR UPDATE` with the committed row
(`populate_existing`), so a redraft and a decision never deadlock and a decision that committed first is never
overwritten (the approval no longer matches the filter and the redraft is refused).
"""

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.contracts import Urgency
from app.db.enums import ActionStatus, ApprovalStatus
from app.db.models import ActionRow, Approval
from app.pipeline import approvals
from app.pipeline.approvals import EDIT_WINDOW, NewRevision


def supersedable(now: datetime) -> Any:
    """Filter: a pending approval, or an edit tap whose window has passed."""
    stale_edit = (Approval.status == ApprovalStatus.edited) & (Approval.decided_at < now - EDIT_WINDOW)
    return (Approval.status == ApprovalStatus.pending) | stale_edit


def lock_live(
    session: Session, company_id: UUID, approval_id: UUID, *, now: datetime
) -> tuple[Approval, ActionRow] | None:
    """The approval (if still supersedable) and its action, locked approval first; None when either moved on."""
    approval = session.scalar(
        select(Approval)
        .where(Approval.id == approval_id, Approval.company_id == company_id, supersedable(now))
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if approval is None:
        return None
    action = approvals.locked_action(session, company_id, approval.action_id)
    if action.status is not ActionStatus.pending_approval or action.draft_version != approval.draft_version:
        return None
    return approval, action


def supersede_draft(
    session: Session,
    company_id: UUID,
    approval_id: UUID,
    variants: list[str],
    *,
    editor: str,
    urgency: Urgency,
    now: datetime,
) -> NewRevision | None:
    """Exactly once: the approval expires and the action gets a new version and approval (`approvals.revise`).
    `editor` is the caller's deterministic key: a retry returns the revision it wrote. None when the draft is no
    longer supersedable (decided, freshly edited or replaced)."""
    if (done := approvals.replayed_edit(session, company_id, editor)) is not None:
        return done
    live = lock_live(session, company_id, approval_id, now=now)
    if live is None:  # moved on meanwhile, or a concurrent run of the same key just committed it
        return approvals.replayed_edit(session, company_id, editor)
    approval, action = live
    approval.status = ApprovalStatus.expired
    return approvals.revise(session, company_id, action, variants, editor=editor, urgency=urgency, now=now)
