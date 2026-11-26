"""Approved actions with no outbound effect: reminders become owner tasks, state updates move the case.

Same approval/version/pause re-checks as the sender; `actions.status = executed` makes a rerun a no-op.
"""

from datetime import datetime
from typing import Literal
from uuid import UUID

from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from app.contracts import ActionType, CaseState
from app.db.enums import ActionStatus, ApprovalStatus, TaskPriority
from app.db.models import ActionRow, Approval, Company
from app.pipeline import case_repo, work_repo

LOCAL_TYPES = frozenset({ActionType.create_reminder, ActionType.update_case_state})
LocalOutcome = Literal["applied", "already", "blocked"]


def _approved(session: Session, action: ActionRow, draft_version: int) -> bool:
    company = session.get(Company, action.company_id)
    approved = session.scalar(
        select(Approval.id).where(
            Approval.company_id == action.company_id,
            Approval.action_id == action.id,
            Approval.draft_version == draft_version,
            Approval.status == ApprovalStatus.approved,
        )
    )
    return bool(company and not company.paused and approved and action.draft_version == draft_version)


def apply_local(engine: Engine, action_id: UUID, draft_version: int) -> LocalOutcome:
    with Session(engine) as session, session.begin():
        action = session.scalar(select(ActionRow).where(ActionRow.id == action_id).with_for_update())
        if action is None or action.type not in LOCAL_TYPES:
            return "blocked"
        if action.status is ActionStatus.executed:
            return "already"
        if action.status is not ActionStatus.approved or not _approved(session, action, draft_version):
            return "blocked"
        payload = action.payload
        if action.type is ActionType.update_case_state:
            new_state = CaseState(payload["new_state"])
            case_repo.transition(
                session, action.company_id, action.case_id, new_state, actor="owner"
            )
            if new_state in (CaseState.resolved, CaseState.closed, CaseState.waiting_on_third_party):
                work_repo.close_case_tasks(session, action.company_id, action.case_id, source="promise")
        else:
            work_repo.create_task(
                session,
                action.company_id,
                title=str(payload["note"]),
                assignee="owner",
                source="reminder",
                case_id=action.case_id,
                action_id=action.id,
                due_at=datetime.fromisoformat(payload["due_at"]),
                priority=TaskPriority.p2,
            )
        action.status = ActionStatus.executed
        return "applied"
