"""Re-checks for executing an approved action, all inside the claim transaction (invariant 5)."""

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.contracts import ButtonChoice
from app.db.enums import ActionStatus, ApprovalStatus, SendStatus
from app.db.models import ActionRow, Approval, Company, Send

_VARIANT = {ButtonChoice.d2: 1, ButtonChoice.d3: 2}


def blocked_reason(session: Session, action: ActionRow, draft_version: int) -> str | None:
    company = session.get(Company, action.company_id)
    if company is None or company.paused:
        return "company paused"
    if action.draft_version != draft_version:
        return "draft version superseded"
    approved = session.scalar(
        select(Approval.id).where(
            Approval.company_id == action.company_id,
            Approval.action_id == action.id,
            Approval.draft_version == draft_version,
            Approval.status == ApprovalStatus.approved,
        )
    )
    if approved is None:
        return "not approved"
    if action.status not in (ActionStatus.approved, ActionStatus.executed):
        return f"action is {action.status.value}"
    return None


def approved_variant(session: Session, action: ActionRow, draft_version: int) -> int:
    choice = session.scalar(
        select(Approval.choice).where(
            Approval.company_id == action.company_id,
            Approval.action_id == action.id,
            Approval.draft_version == draft_version,
            Approval.status == ApprovalStatus.approved,
        )
    )
    return _VARIANT.get(choice, 0) if choice else 0


def locked_action(session: Session, action_id: UUID) -> ActionRow | None:
    """Company row first (FOR NO KEY UPDATE: pause/mode flips wait for this claim), then the action row."""
    company_id = session.scalar(select(ActionRow.company_id).where(ActionRow.id == action_id))
    if company_id is None:
        return None
    session.scalar(select(Company).where(Company.id == company_id).with_for_update(key_share=True))
    return session.scalar(
        select(ActionRow).where(ActionRow.id == action_id, ActionRow.company_id == company_id).with_for_update()
    )


def sent_row(session: Session, company_id: UUID, key: str) -> Send | None:
    return session.scalar(
        select(Send).where(Send.company_id == company_id, Send.idempotency_key == key, Send.status == SendStatus.sent)
    )
