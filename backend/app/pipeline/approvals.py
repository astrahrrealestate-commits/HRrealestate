"""Owner approvals: one live approval per draft version, button decisions, owner edit → new revision (`revise`, also
used by the owner-requested redraft in `supersede`).

Decisions lock the approval row (`FOR UPDATE`), so a duplicate or late tap returns the first decision unchanged and
can never approve a second variant. Execution itself is the sender's job (`exec:{action_id}:{draft_version}`).
"""

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Literal
from uuid import UUID

from sqlalchemy import String, cast, exists, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.contracts import ActionType, ButtonChoice, Urgency
from app.core.errors import NotFoundError
from app.db.enums import ActionStatus, ApprovalStatus, SendStatus, TaskPriority
from app.db.models import ActionRevision, ActionRow, Approval, Send
from app.llm.agents.proposer import Persona
from app.pipeline import work_repo

EDIT_WINDOW = timedelta(hours=24)
TASK_DUE = {
    Urgency.emergency: timedelta(hours=1),
    Urgency.high: timedelta(hours=4),
    Urgency.normal: timedelta(hours=24),
    Urgency.low: timedelta(hours=72),
}
TASK_PRIORITY = {
    Urgency.emergency: TaskPriority.p1,
    Urgency.high: TaskPriority.p1,
    Urgency.normal: TaskPriority.p2,
    Urgency.low: TaskPriority.p3,
}
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
            Approval.company_id == company_id,
            Approval.action_id == action_id,
            Approval.draft_version == draft_version,
            Approval.status.in_([ApprovalStatus.pending, ApprovalStatus.approved]),
        )
    ).scalar_one()
    work_repo.create_task(
        session,
        company_id,
        title="Approve proposed action",
        assignee="owner",
        source="approval",
        case_id=_action(session, company_id, action_id).case_id,
        action_id=action_id,
        due_at=now + TASK_DUE[urgency],
        priority=TASK_PRIORITY[urgency],
    )
    return approval_id


def _action(session: Session, company_id: UUID, action_id: UUID) -> ActionRow:
    action = session.scalar(select(ActionRow).where(ActionRow.id == action_id, ActionRow.company_id == company_id))
    if action is None:
        raise NotFoundError(f"action {action_id} not found")
    return action


def locked_action(session: Session, company_id: UUID, action_id: UUID) -> ActionRow:
    action = session.scalar(
        select(ActionRow)
        .where(ActionRow.id == action_id, ActionRow.company_id == company_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
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
        select(Approval)
        .where(Approval.id == approval_id, Approval.company_id == company_id)
        .with_for_update()
        .execution_options(populate_existing=True)  # the committed row, never a copy loaded before the lock
    )
    if approval is None:
        raise NotFoundError(f"approval {approval_id} not found")
    if approval.status is not ApprovalStatus.pending:  # decided, or expired by a redraft that committed first
        return _previous(approval)
    action = locked_action(session, company_id, approval.action_id)  # approval, then action (redraft's order)
    if action.draft_version != approval.draft_version:  # superseded by an edit or a redraft
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


def replayed_edit(session: Session, company_id: UUID, editor: str) -> NewRevision | None:
    """The same owner message already produced a revision (a step re-run after commit): return it unchanged."""
    row = session.execute(
        select(ActionRevision.action_id, ActionRevision.draft_version, Approval.id)
        .join(
            Approval,
            (Approval.action_id == ActionRevision.action_id) & (Approval.draft_version == ActionRevision.draft_version),
        )
        .where(ActionRevision.company_id == company_id, ActionRevision.edited_by == editor)
    ).first()
    return NewRevision(row[0], row[1], row[2]) if row else None


def apply_owner_edit(
    session: Session,
    company_id: UUID,
    text: str,
    *,
    now: datetime,
    message_id: UUID | None = None,
    approval_id: UUID | None = None,
) -> NewRevision | None:
    """The owner's next text after tapping `edit` becomes draft_version + 1 with one variant, plus a new approval.
    Blank text never replaces a draft. `message_id` makes a re-run of the same message return its revision.
    `approval_id` (dashboard) targets exactly that approval instead of the latest edited one."""
    editor = f"owner:{message_id}" if message_id else "owner"
    if message_id is not None and (done := replayed_edit(session, company_id, editor)) is not None:
        return done
    if not text.strip():
        return None
    target = [Approval.id == approval_id] if approval_id is not None else []
    pending_edit = session.execute(
        select(Approval, ActionRow)
        .join(ActionRow, ActionRow.id == Approval.action_id)
        .where(
            Approval.company_id == company_id,
            Approval.status == ApprovalStatus.edited,
            *target,
            Approval.decided_at >= now - EDIT_WINDOW,
            ActionRow.draft_version == Approval.draft_version,
            ActionRow.status == ActionStatus.pending_approval,
        )
        .order_by(Approval.decided_at.desc())
        .limit(1)
        .with_for_update(of=ActionRow)
    ).first()
    if pending_edit is None:
        return None
    _, action = pending_edit
    return revise(session, company_id, action, [text], editor=editor, urgency=Urgency.normal, now=now)


def revise(
    session: Session,
    company_id: UUID,
    action: ActionRow,
    variants: list[str],
    *,
    editor: str,
    urgency: Urgency,
    now: datetime,
    persona: Persona | None = None,
    commitments: list[str] | None = None,
) -> NewRevision:
    """The revision path (owner edit, owner-requested redraft): `draft_version + 1` with new variants (channel and
    subject stay the action's own), an ActionRevision row keyed by `editor`, and a new pending approval.
    `persona` is the one a redraft was written in; an owner's own edit passes none, so the draft stops claiming one."""
    payload: dict[str, Any] = {**action.payload, "body_variants": variants}
    if commitments is not None:
        payload["commitments"] = commitments
    action.draft_version += 1
    action.payload = payload
    action.persona_name = persona.name if persona else None
    action.persona_version = persona.version if persona else None
    session.add(
        ActionRevision(
            company_id=company_id,
            action_id=action.id,
            draft_version=action.draft_version,
            payload=payload,
            edited_by=editor,
        )
    )
    session.flush()
    approval_id = open_approval(session, company_id, action.id, action.draft_version, urgency=urgency, now=now)
    return NewRevision(action.id, action.draft_version, approval_id)


def exec_send(company_id: UUID) -> Any:
    """Correlated filter: a `sends` row of the company under the action's current `exec:{action_id}:{version}` key
    (the sender's `exec_key`, built in SQL)."""
    key = "exec:" + cast(ActionRow.id, String) + ":" + cast(ActionRow.draft_version, String)
    return (Send.company_id == company_id) & (Send.action_id == ActionRow.id) & (Send.idempotency_key == key)


def approved_unexecuted(session: Session, company_id: UUID) -> list[tuple[UUID, int, ActionType]]:
    """Approved actions that never ran (blocked while paused): `resume` re-runs them. An action whose exec send is
    held (`sending`) or finished (`sent`/`failed`) is skipped: only a missing or `pending` row may run again."""
    held = exists().where(exec_send(company_id), Send.status != SendStatus.pending)
    rows = session.execute(
        select(ActionRow.id, ActionRow.draft_version, ActionRow.type)
        .join(Approval, (Approval.action_id == ActionRow.id) & (Approval.draft_version == ActionRow.draft_version))
        .where(
            ActionRow.company_id == company_id,
            ActionRow.status == ActionStatus.approved,
            Approval.status == ApprovalStatus.approved,
            ~held,
        )
    ).all()
    return [(r[0], r[1], r[2]) for r in rows]
