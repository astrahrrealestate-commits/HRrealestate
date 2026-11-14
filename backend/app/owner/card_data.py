"""Read what an approval card shows from the DB (company-scoped)."""

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.contracts import ActionType
from app.core.errors import NotFoundError
from app.db.models import ActionRow, Approval, Case, Person, UnderstandingRow
from app.owner.cards import ApprovalCard

KIND_LABEL = {
    ActionType.reply_draft: "Reply",
    ActionType.request_contractor: "Contractor request",
    ActionType.notify_owner: "Notice",
    ActionType.escalate: "Escalation",
    ActionType.create_reminder: "Reminder",
    ActionType.update_case_state: "Case status",
}


def case_label(session: Session, case: Case) -> str:
    name = (
        session.scalar(
            select(Person.display_name).where(Person.company_id == case.company_id, Person.id == case.primary_person_id)
        )
        or "Unknown sender"
    )
    return f"{name} · {case.category.value}"


def _intent(session: Session, action: ActionRow, case: Case) -> str:
    intent = session.scalar(
        select(UnderstandingRow.body["intent"].astext).where(
            UnderstandingRow.company_id == action.company_id, UnderstandingRow.message_id.in_(action.context_ref)
        )
    )
    return intent or (case.summary.splitlines()[0] if case.summary else action.rationale)


def _detail(action: ActionRow) -> str | None:
    p = action.payload
    detail = {
        ActionType.notify_owner: p.get("text"),
        ActionType.escalate: p.get("reason"),
        ActionType.create_reminder: f"{p.get('note')} (due {p.get('due_at')})",
        ActionType.update_case_state: f"Set case to {p.get('new_state')}",
    }.get(action.type)
    return str(detail) if detail else None


def load_card(session: Session, company_id: UUID, approval_id: UUID) -> ApprovalCard:
    row = session.execute(
        select(Approval, ActionRow, Case)
        .join(ActionRow, ActionRow.id == Approval.action_id)
        .join(Case, Case.id == ActionRow.case_id)
        .where(Approval.id == approval_id, Approval.company_id == company_id)
    ).first()
    if row is None:
        raise NotFoundError(f"approval {approval_id} not found")
    approval, action, case = row
    drafts = tuple(action.payload.get("body_variants") or ())
    return ApprovalCard(
        approval.id,
        case_label(session, case),
        case.urgency,
        _intent(session, action, case),
        KIND_LABEL[action.type],
        drafts,
        _detail(action),
    )
