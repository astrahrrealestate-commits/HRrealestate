"""Dashboard decisions on approvals: the WhatsApp button rules plus the suspicious-sender confirmation gate.

Execution is never started here: the caller commits, then enqueues `exec:{action_id}:{draft_version}`.
"""

from collections.abc import Iterable
from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.contracts import ButtonChoice
from app.core.errors import EstateOSError, NotFoundError
from app.db.enums import ApprovalStatus, FeedKind
from app.db.models import ActionRow, Approval, CaseLink, OwnerFeed, UnderstandingRow
from app.pipeline import approvals

NON_APPROVING = frozenset({ButtonChoice.edit, ButtonChoice.rej})


class SuspiciousNeedsConfirmError(EstateOSError):
    """The case's latest message was flagged suspicious: approving needs an explicit confirmation."""


class NotEditableError(EstateOSError):
    """The approval is no longer the live draft, or the new text is blank."""


def any_flagged(bodies: Iterable[dict[str, Any] | None]) -> bool:
    return any(bool(((b or {}).get("suspicious") or {}).get("flag", False)) for b in bodies)


def is_suspicious(session: Session, company_id: UUID, action: ActionRow) -> bool:
    """Any message the action answers (`context_ref`) was flagged; follow-ups with no refs fall back to the case."""
    stmt = select(UnderstandingRow.body).where(UnderstandingRow.company_id == company_id)
    if action.context_ref:
        stmt = stmt.where(UnderstandingRow.message_id.in_(action.context_ref))
    else:
        stmt = stmt.join(CaseLink, CaseLink.message_id == UnderstandingRow.message_id).where(
            CaseLink.company_id == company_id, CaseLink.case_id == action.case_id
        )
    return any_flagged(session.scalars(stmt).all())


def _approval_action(session: Session, company_id: UUID, approval_id: UUID) -> tuple[Approval, ActionRow]:
    row = session.execute(
        select(Approval, ActionRow)
        .join(ActionRow, Approval.action_id == ActionRow.id)
        .where(Approval.id == approval_id, Approval.company_id == company_id, ActionRow.company_id == company_id)
    ).first()
    if row is None:
        raise NotFoundError(f"approval {approval_id} not found")
    return row[0], row[1]


def resolve_feed(session: Session, company_id: UUID, approval_id: UUID, *, at: datetime) -> None:
    session.execute(
        update(OwnerFeed)
        .where(
            OwnerFeed.company_id == company_id,
            OwnerFeed.kind == FeedKind.approval,
            OwnerFeed.ref_id == approval_id,
            OwnerFeed.resolved_at.is_(None),
        )
        .values(resolved_at=at)
    )


def decide_approval(
    session: Session,
    company_id: UUID,
    approval_id: UUID,
    choice: ButtonChoice,
    *,
    at: datetime,
    confirm_suspicious: bool,
) -> approvals.Decision:
    approval, action = _approval_action(session, company_id, approval_id)
    gated = approval.status is ApprovalStatus.pending and choice not in NON_APPROVING and not confirm_suspicious
    if gated and is_suspicious(session, company_id, action):
        raise SuspiciousNeedsConfirmError("suspicious sender: confirmation required")
    decision = approvals.decide(session, company_id, approval_id, choice, at=at)
    resolve_feed(session, company_id, approval_id, at=at)
    return decision


def edit_approval(
    session: Session, company_id: UUID, approval_id: UUID, text: str, *, at: datetime
) -> approvals.NewRevision:
    """Edit the live draft: marks the approval edited, then writes `draft_version + 1` with the new text."""
    if not text.strip():
        raise NotEditableError("blank text never replaces a draft")
    decision = approvals.decide(session, company_id, approval_id, ButtonChoice.edit, at=at)
    revision = (
        approvals.apply_owner_edit(session, company_id, text, now=at, approval_id=approval_id)
        if decision.kind == "edit"
        else None
    )
    if revision is None or revision.action_id != decision.action_id:
        raise NotEditableError("approval is not the live draft")
    resolve_feed(session, company_id, approval_id, at=at)
    return revision
