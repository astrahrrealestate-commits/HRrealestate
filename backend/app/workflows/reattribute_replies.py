"""Unsent replies on a repaired case are cancelled (see `app.workflows.reattribute`).

They were written while the mail looked like ours, and a send takes its recipient from the case at send time, so an
approved one could reach another person after the repair. Resume and a repeat click can still run an approved reply,
so those go too. Finished replies keep their history. Cases themselves are not changed.
"""

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.contracts import ActionType
from app.core.errors import EstateOSError
from app.db.enums import ActionStatus, ApprovalStatus, CaseEventKind, SendStatus
from app.db.models import ActionRow, Approval, CaseEvent, Send
from app.pipeline.approvals import exec_send
from app.pipeline.dashboard_decisions import resolve_feed
from app.pipeline.work_repo import close_action_tasks

_UNSENT = (ActionStatus.proposed, ActionStatus.pending_approval, ActionStatus.paused, ActionStatus.approved)
_LIVE = (ApprovalStatus.pending, ApprovalStatus.edited, ApprovalStatus.approved)


class RepairRefusedError(EstateOSError):
    """The repair cannot run safely right now; nothing was changed."""


@dataclass(frozen=True)
class CancelledReply:
    case_id: UUID
    action_id: UUID
    was: str


@dataclass(frozen=True)
class CaseToCheck:
    """A case holding repaired mail. Its contact and flat were not changed."""

    case_id: UUID
    senders: tuple[str, ...]


def _unclaim(session: Session, company_id: UUID, action_id: UUID) -> bool:
    """False when the reply already finished. A claimed but not yet attempted send is failed, so it can never start;
    one being delivered right now stops the run."""
    send = session.scalar(select(Send).where(exec_send(company_id), ActionRow.id == action_id).with_for_update(of=Send))
    if send is None:
        return True
    if send.status is SendStatus.sending:
        raise RepairRefusedError(f"a send of action {action_id} is in progress; run again when it has finished")
    if send.status is not SendStatus.pending:
        return False
    send.status, send.error = SendStatus.failed, "cancelled: the mail it answers got its original sender"
    return True


def _cancel(session: Session, company_id: UUID, action: ActionRow, at: datetime) -> CancelledReply:
    approvals = session.scalars(
        select(Approval)
        .where(
            Approval.company_id == company_id,
            Approval.action_id == action.id,
            Approval.draft_version == action.draft_version,
            Approval.status.in_(_LIVE),
        )
        .with_for_update()
    ).all()
    before = ", ".join(f"{a.id} was {a.status.value}" for a in approvals) or "none"
    for approval in approvals:
        approval.status = ApprovalStatus.expired
        resolve_feed(session, company_id, approval.id, at=at)
    was = action.status.value
    action.status = ActionStatus.superseded
    close_action_tasks(session, company_id, action.id)
    note = f"forwarded-mail repair cancelled reply {action.id}: action was {was}; approvals: {before}"
    session.add(
        CaseEvent(company_id=company_id, case_id=action.case_id, kind=CaseEventKind.note, note=note, actor="system")
    )
    return CancelledReply(action.case_id, action.id, was)


def cancel_unsent_replies(
    session: Session, company_id: UUID, case_ids: Iterable[UUID], *, at: datetime
) -> list[CancelledReply]:
    """The caller holds the company row lock the sender takes before claiming a send."""
    actions = session.scalars(
        select(ActionRow)
        .where(
            ActionRow.company_id == company_id,
            ActionRow.case_id.in_(list(case_ids)),
            ActionRow.type == ActionType.reply_draft,
            ActionRow.status.in_(_UNSENT),
        )
        .order_by(ActionRow.id)
        .with_for_update()
    ).all()
    return [_cancel(session, company_id, a, at) for a in actions if _unclaim(session, company_id, a.id)]
