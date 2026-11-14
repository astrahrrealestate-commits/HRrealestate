"""Dashboard reads: pending approvals and documents awaiting the owner's filing choice. Company-scoped."""

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from sqlalchemy import select, tuple_
from sqlalchemy.orm import Session

from app.contracts import ActionType
from app.db.enums import ApprovalStatus, DocumentStatus
from app.db.models import ActionRow, Approval, AttachmentRow, Case, CaseLink, DocumentRow, Person
from app.pipeline.dashboard_decisions import suspicious_by_action
from app.pipeline.read_repo import MAX_PAGE, Cursor


@dataclass(frozen=True)
class PendingApproval:
    id: UUID
    action_id: UUID
    action_type: ActionType
    case_id: UUID
    case_label: str
    drafts: tuple[str, ...]
    draft_version: int
    suspicious: bool
    created_at: datetime


@dataclass(frozen=True)
class ReviewDocument:
    id: UUID  # the documents row: pagination tiebreak
    attachment_id: UUID
    filename: str | None
    mime_type: str
    case_id: UUID | None
    suggested_type: str
    created_at: datetime


UNKNOWN_SENDER = "Unknown sender"  # same label as the WhatsApp card (app.owner.card_data.case_label)


def _cap(limit: int) -> int:
    return max(1, min(limit, MAX_PAGE))


def pending_approvals(session: Session, company_id: UUID, after: Cursor | None, limit: int) -> list[PendingApproval]:
    q = (
        select(Approval, ActionRow, Case, Person.display_name)
        .join(ActionRow, ActionRow.id == Approval.action_id)
        .join(Case, Case.id == ActionRow.case_id)
        .outerjoin(Person, (Person.id == Case.primary_person_id) & (Person.company_id == company_id))
        .where(
            Approval.company_id == company_id,
            ActionRow.company_id == company_id,
            Case.company_id == company_id,
            Approval.status == ApprovalStatus.pending,
            Approval.draft_version == ActionRow.draft_version,
        )
    )
    if after is not None:
        q = q.where(tuple_(Approval.created_at, Approval.id) > tuple_(*after))
    rows = session.execute(q.order_by(Approval.created_at, Approval.id).limit(_cap(limit))).all()
    flags = suspicious_by_action(session, company_id, [action for _, action, _, _ in rows])
    return [
        PendingApproval(
            id=approval.id,
            action_id=action.id,
            action_type=action.type,
            case_id=case.id,
            case_label=f"{name or UNKNOWN_SENDER} · {case.category.value}",
            drafts=tuple(action.payload.get("body_variants") or ()),
            draft_version=approval.draft_version,
            suspicious=flags[action.id],
            created_at=approval.created_at,
        )
        for approval, action, case, name in rows
    ]


def _case_ids(session: Session, company_id: UUID, message_ids: list[UUID]) -> dict[UUID, UUID]:
    """Message -> case; when a message has several links the oldest one wins (deterministic)."""
    rows = session.execute(
        select(CaseLink.message_id, CaseLink.case_id)
        .where(CaseLink.company_id == company_id, CaseLink.message_id.in_(message_ids))
        .order_by(CaseLink.created_at, CaseLink.id)
    )
    found: dict[UUID, UUID] = {}
    for message_id, case_id in rows:
        found.setdefault(message_id, case_id)
    return found


def review_documents(session: Session, company_id: UUID, after: Cursor | None, limit: int) -> list[ReviewDocument]:
    """Documents with status `review`: low confidence or over budget, waiting for the owner's filing choice."""
    q = (
        select(DocumentRow, AttachmentRow)
        .join(AttachmentRow, AttachmentRow.id == DocumentRow.attachment_id)
        .where(
            DocumentRow.company_id == company_id,
            AttachmentRow.company_id == company_id,
            DocumentRow.status == DocumentStatus.review,
        )
    )
    if after is not None:
        q = q.where(tuple_(DocumentRow.created_at, DocumentRow.id) > tuple_(*after))
    rows = session.execute(q.order_by(DocumentRow.created_at, DocumentRow.id).limit(_cap(limit))).all()
    cases = _case_ids(session, company_id, [a.message_id for _, a in rows])
    return [
        ReviewDocument(
            id=d.id,
            attachment_id=a.id,
            filename=a.filename or d.file_name or None,
            mime_type=a.mime_type,
            case_id=cases.get(a.message_id),
            suggested_type=d.doc_type,
            created_at=d.created_at,
        )
        for d, a in rows
    ]
