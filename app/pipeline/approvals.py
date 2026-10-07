"""Owner approvals: one live approval per draft version, button decisions, owner edit → new revision.

Decisions lock the approval row (`FOR UPDATE`), so a duplicate or late tap returns the first decision unchanged and
can never approve a second variant. Execution itself is the sender's job (`exec:{action_id}:{draft_version}`).
"""

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Literal
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.contracts import ButtonChoice, Urgency
from app.core.errors import NotFoundError
from app.db.enums import ActionStatus, ApprovalStatus, TaskPriority
from app.db.models import ActionRevision, ActionRow, Approval
from app.pipeline import work_repo

EDIT_WINDOW = timedelta(hours=24)
TASK_DUE = {Urgency.emergency: timedelta(hours=1), Urgency.high: timedelta(hours=4),
            Urgency.normal: timedelta(hours=24), Urgency.low: timedelta(hours=72)}  # fmt: skip
TASK_PRIORITY = {Urgency.emergency: TaskPriority.p1, Urgency.high: TaskPriority.p1,
                 Urgency.normal: TaskPriority.p2, Urgency.low: TaskPriority.p3}  # fmt: skip
_VARIANT = {ButtonChoice.ok: 0, ButtonChoice.d1: 0, ButtonChoice.d2: 1, ButtonChoice.d3: 2}

DecisionKind = Literal["execute", "edit", "rejected", "stale"]


@dataclass(frozen=True)
class Decision:
    kind: DecisionKind
    action_id: UUID
    draft_version: int
    variant: int | None = None


@dataclass(frozen=True)
class NewRevision:
    action_id: UUID
    draft_version: int
    approval_id: UUID


def open_approval(
    session: Session, company_id: UUID, action_id: UUID, draft_version: int, *, urgency: Urgency, now: datetime
) -> UUID:
    session.execute(
        insert(Approval)
        .values(company_id=company_id, action_id=action_id, draft_version=draft_version)
        .on_conflict_do_nothing(
            index_elements=["action_id", "draft_version"],
            index_where=Approval.status.in_([ApprovalStatus.pending, ApprovalStatus.approved]),
        )
    )
    approval_id = session.execute(
        select(Approval.id).where(
            Approval.company_id == company_id, Approval.action_id == action_id, Approval.draft_version == draft_version,
            Approval.status.in_([ApprovalStatus.pending, ApprovalStatus.approved]),
        )
    ).scalar_one()  # fmt: skip
    work_repo.create_task(
        session, company_id, title="Approve proposed action", assignee="owner", source="approval",
        case_id=_action(session, company_id, action_id).case_id, action_id=action_id,
        due_at=now + TASK_DUE[urgency], priority=TASK_PRIORITY[urgency],
    )  # fmt: skip
    return approval_id


def _action(session: Session, company_id: UUID, action_id: UUID) -> ActionRow:
    action = session.scalar(select(ActionRow).where(ActionRow.id == action_id, ActionRow.company_id == company_id))
    if action is None:
        raise NotFoundError(f"action {action_id} not found")
    return action


def _previous(approval: Approval) -> Decision:
    if approval.status is ApprovalStatus.approved:
        return Decision(
            "execute", approval.action_id, approval.draft_version, _VARIANT.get(approval.choice or ButtonChoice.ok)
        )
    kind: DecisionKind = {ApprovalStatus.rejected: "rejected", ApprovalStatus.edited: "edit"}.get(
        approval.status, "stale"
    )  # type: ignore[assignment]  # literal values
    return Decision(kind, approval.action_id, approval.draft_version)


def decide(session: Session, company_id: UUID, approval_id: UUID, choice: ButtonChoice, *, at: datetime) -> Decision:
    approval = session.scalar(
        select(Approval).where(Approval.id == approval_id, Approval.company_id == company_id).with_for_update()
    )
    if approval is None:
        raise NotFoundError(f"approval {approval_id} not found")
    if approval.status is not ApprovalStatus.pending:
        return _previous(approval)
    action = _action(session, company_id, approval.action_id)
    if action.draft_version != approval.draft_version:  # superseded by an edit
        approval.status = ApprovalStatus.expired
        session.flush()
        return Decision("stale", action.id, approval.draft_version)
    approval.choice, approval.decided_at = choice, at
    if choice is ButtonChoice.edit:
        approval.status = ApprovalStatus.edited
    elif choice is ButtonChoice.rej:
        approval.status, action.status = ApprovalStatus.rejected, ActionStatus.rejected
        work_repo.close_action_tasks(session, company_id, action.id)
    else:
        approval.status, action.status = ApprovalStatus.approved, ActionStatus.approved
        work_repo.close_action_tasks(session, company_id, action.id)
    session.flush()
    return _previous(approval)


def apply_owner_edit(session: Session, company_id: UUID, text: str, *, now: datetime) -> NewRevision | None:
    """The owner's next text after tapping `edit` becomes draft_version + 1 with one variant, plus a new approval."""
    pending_edit = session.execute(
        select(Approval, ActionRow)
        .join(ActionRow, ActionRow.id == Approval.action_id)
        .where(
            Approval.company_id == company_id, Approval.status == ApprovalStatus.edited,
            Approval.decided_at >= now - EDIT_WINDOW, ActionRow.draft_version == Approval.draft_version,
            ActionRow.status == ActionStatus.pending_approval,
        )
        .order_by(Approval.decided_at.desc())
        .limit(1)
        .with_for_update(of=ActionRow)
    ).first()  # fmt: skip
    if pending_edit is None:
        return None
    _, action = pending_edit
    payload: dict[str, Any] = {**action.payload, "body_variants": [text]}
    action.draft_version += 1
    action.payload = payload
    session.add(ActionRevision(company_id=company_id, action_id=action.id, draft_version=action.draft_version,
                               payload=payload, edited_by="owner"))  # fmt: skip
    session.flush()
    approval_id = open_approval(session, company_id, action.id, action.draft_version, urgency=Urgency.normal, now=now)
    return NewRevision(action.id, action.draft_version, approval_id)
