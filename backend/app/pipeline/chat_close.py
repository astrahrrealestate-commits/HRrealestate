"""Closing the AI draft behind an owner-typed chat message (ADR 0013, spec section 5.3 point 8).

Harjot picked a suggestion in the composer, edited it or not, and sent it himself. The reply draft is then handled by
hand: its action becomes `superseded` (the existing "replaced by something else" terminal status; nothing is sent
for it) and its pending approval expires, so the approvals list does not keep a stale card whose approve click
would send a second message. Locks follow `approvals.decide`: approval first, then the action.
"""

from uuid import UUID

from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from app.contracts import ActionType, Channel, Direction
from app.db.enums import ActionStatus, ApprovalStatus
from app.db.models import ActionRow, Approval, MessageRow
from app.pipeline import work_repo
from app.pipeline.chat_repo import OPEN_DRAFT


def _suggestion(session: Session, company_id: UUID, message_id: UUID) -> tuple[UUID, str] | None:
    """(action id, chat thread) the stored outbound message names, or None."""
    row = session.execute(
        select(MessageRow.meta, MessageRow.thread_ref).where(
            MessageRow.id == message_id,
            MessageRow.company_id == company_id,
            MessageRow.channel == Channel.whatsapp,
            MessageRow.direction == Direction.outbound,
        )
    ).first()
    raw = row[0].get("suggestion_action_id") if row else None
    if row is None or not isinstance(raw, str) or not row[1]:
        return None
    try:
        return UUID(raw), row[1]
    except ValueError:
        return None


def _in_chat(session: Session, company_id: UUID, action: ActionRow, thread: str) -> bool:
    """The draft answers an inbound message of this very chat (its `context_ref`), never another contact's."""
    found = session.scalar(
        select(MessageRow.id)
        .where(
            MessageRow.company_id == company_id,
            MessageRow.id.in_(action.context_ref),
            MessageRow.channel == Channel.whatsapp,
            MessageRow.direction == Direction.inbound,
            MessageRow.thread_ref == thread,
        )
        .limit(1)
    )
    return found is not None


def close_suggestion(engine: Engine, company_id: UUID, message_id: UUID) -> bool:
    """Supersede the reply draft the message came from. Idempotent; True only when this call closed it.

    Only an open `reply_draft` of this company that answers a message of this message's own chat is touched: one that
    was approved, executed or already closed in the meantime, or belongs to another chat, is left exactly as it is."""
    with Session(engine) as session, session.begin():
        named = _suggestion(session, company_id, message_id)
        if named is None:
            return False
        action_id, thread = named
        live = session.scalars(
            select(Approval)
            .where(
                Approval.company_id == company_id,
                Approval.action_id == action_id,
                Approval.status == ApprovalStatus.pending,
            )
            .with_for_update()
        ).all()
        action = session.scalar(
            select(ActionRow)
            .where(
                ActionRow.id == action_id,
                ActionRow.company_id == company_id,
                ActionRow.type == ActionType.reply_draft,
                ActionRow.status.in_(OPEN_DRAFT),
            )
            .with_for_update()
        )
        if action is None or not _in_chat(session, company_id, action, thread):
            return False
        for approval in live:
            approval.status = ApprovalStatus.expired
        action.status = ActionStatus.superseded
        work_repo.close_action_tasks(session, company_id, action_id)
    return True
