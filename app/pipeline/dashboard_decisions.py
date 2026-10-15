"""Dashboard decisions on approvals: the WhatsApp button rules plus the suspicious-sender confirmation gate.

Execution is never started here: the caller commits, then enqueues `exec:{action_id}:{draft_version}`.
"""

from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
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


def flags_for(
    actions: Sequence[ActionRow],
    by_message: Mapping[UUID, list[dict[str, Any] | None]],
    by_case: Mapping[UUID, list[dict[str, Any] | None]],
) -> dict[UUID, bool]:
    """Pure gate predicate: any message in `context_ref` flagged; no refs falls back to the case's messages."""
    return {
        a.id: any_flagged(body for m in a.context_ref for body in by_message.get(m, []))
        if a.context_ref
        else any_flagged(by_case.get(a.case_id, []))
        for a in actions
    }


def suspicious_by_action(session: Session, company_id: UUID, actions: Sequence[ActionRow]) -> dict[UUID, bool]:
    """The decide gate's suspicious flag for many actions in at most two queries."""
    refs = {m for a in actions for m in a.context_ref}
    by_message: dict[UUID, list[dict[str, Any] | None]] = defaultdict(list)
    if refs:
        q = select(UnderstandingRow.message_id, UnderstandingRow.body).where(
            UnderstandingRow.company_id == company_id, UnderstandingRow.message_id.in_(refs)
        )
        for message_id, body in session.execute(q):
            by_message[message_id].append(body)
    cases = {a.case_id for a in actions if not a.context_ref}
    by_case: dict[UUID, list[dict[str, Any] | None]] = defaultdict(list)
    if cases:
        q2 = (
            select(CaseLink.case_id, UnderstandingRow.body)
            .join(UnderstandingRow, CaseLink.message_id == UnderstandingRow.message_id)
            .where(
                CaseLink.company_id == company_id,
                UnderstandingRow.company_id == company_id,
                CaseLink.case_id.in_(cases),
            )
        )
        for case_id, body in session.execute(q2):
            by_case[case_id].append(body)
    return flags_for(actions, by_message, by_case)


def is_suspicious(session: Session, company_id: UUID, action: ActionRow) -> bool:
    """Any message the action answers (`context_ref`) was flagged; follow-ups with no refs fall back to the case."""
    return suspicious_by_action(session, company_id, [action])[action.id]


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
