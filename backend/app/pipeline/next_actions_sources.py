"""Approval and reply-needed loaders for category next actions (M13 T10). Every query filters by `company_id`."""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.context.message_origin import is_owner_authored
from app.contracts import ActionType, Category, Direction
from app.contracts.categories import current_category
from app.db.enums import ActionStatus, ApprovalStatus
from app.db.models import ActionRow, Approval, Case, CaseLink, MessageRow, Person, UnderstandingRow
from app.db.models.ingestion import not_chat_only
from app.pipeline.next_actions_items import (
    OPEN_STATES,
    ActionKind,
    ActionViewer,
    NextAction,
    as_utc,
    load_document_reviews,
    load_overdue_waits,
    load_quote_reviews,
    one_line,
)

__all__ = ["ActionKind", "ActionViewer", "NextAction", "RankedItem", "all_pipeline_items"]


@dataclass(frozen=True)
class RankedItem:
    action: NextAction
    created_at: datetime


def _first_draft_line(payload: dict[str, object]) -> str | None:
    variants = payload.get("body_variants")
    if isinstance(variants, list) and variants and isinstance(variants[0], str):
        first = one_line(variants[0], 180)
        return first or None
    return None


def load_approvals(session: Session, company_id: UUID, viewer: ActionViewer) -> list[RankedItem]:
    rows = session.execute(
        select(Approval, ActionRow, Case, Person.display_name)
        .join(ActionRow, (ActionRow.id == Approval.action_id) & (ActionRow.company_id == company_id))
        .join(Case, (Case.id == ActionRow.case_id) & (Case.company_id == company_id))
        .outerjoin(Person, (Person.id == Case.primary_person_id) & (Person.company_id == company_id))
        .where(
            Approval.company_id == company_id,
            Approval.status == ApprovalStatus.pending,
            ActionRow.type == ActionType.reply_draft,
            ActionRow.status != ActionStatus.rejected,
        )
    ).all()
    out: list[RankedItem] = []
    for approval, action, case, name in rows:
        cat = current_category(case.category.value)
        if cat is Category.spam:
            continue
        party = viewer.party(name)
        why = (one_line(case.summary) if viewer.inbox else "") or "Reply draft ready for approval"
        prepared = _first_draft_line(action.payload) if viewer.inbox else None
        out.append(
            RankedItem(
                NextAction(
                    id=f"approval:{approval.id}",
                    category=cat,
                    kind="approve_draft",
                    title=f"Approve reply to {party}",
                    why=why,
                    urgency=case.urgency,
                    due_at=None,
                    case_id=case.id,
                    approval_id=approval.id,
                    prepared=prepared,
                    target_url=f"/inbox?thread={case.id}",
                ),
                as_utc(approval.created_at),
            )
        )
    return out


def load_replies_needed(session: Session, company_id: UUID, viewer: ActionViewer) -> list[RankedItem]:
    live_cases = set(
        session.scalars(
            select(ActionRow.case_id)
            .join(Approval, (Approval.action_id == ActionRow.id) & (Approval.company_id == company_id))
            .where(
                Approval.company_id == company_id,
                Approval.status.in_([ApprovalStatus.pending, ApprovalStatus.approved]),
                ActionRow.type == ActionType.reply_draft,
            )
        ).all()
    )
    cases = list(
        session.execute(
            select(Case, Person.display_name)
            .outerjoin(Person, (Person.id == Case.primary_person_id) & (Person.company_id == company_id))
            .where(Case.company_id == company_id, Case.state.in_(OPEN_STATES))
        ).all()
    )
    out: list[RankedItem] = []
    for case, name in cases:
        cat = current_category(case.category.value)
        if cat is Category.spam or case.id in live_cases:
            continue
        newest = session.scalar(
            select(MessageRow)
            .join(CaseLink, (CaseLink.message_id == MessageRow.id) & (CaseLink.company_id == company_id))
            .where(CaseLink.company_id == company_id, CaseLink.case_id == case.id, not_chat_only())
            .order_by(MessageRow.sent_at.desc(), MessageRow.id.desc())
            .limit(1)
        )
        if newest is None or newest.direction is Direction.outbound or is_owner_authored(newest):
            continue
        body = session.scalar(
            select(UnderstandingRow.body).where(
                UnderstandingRow.company_id == company_id, UnderstandingRow.message_id == newest.id
            )
        )
        if not (isinstance(body, dict) and body.get("requires_reply")):
            continue
        party = viewer.party(name)
        why = (one_line(case.summary) if viewer.inbox else "") or "Inbound message awaiting reply"
        out.append(
            RankedItem(
                NextAction(
                    id=f"reply:{case.id}",
                    category=cat,
                    kind="reply_needed",
                    title=f"Reply needed · {party}",
                    why=why,
                    urgency=case.urgency,
                    due_at=None,
                    case_id=case.id,
                    approval_id=None,
                    prepared="Draft with Astra" if viewer.inbox else None,
                    target_url=f"/inbox?thread={case.id}",
                ),
                as_utc(newest.sent_at),
            )
        )
    return out


def all_pipeline_items(
    session: Session, company_id: UUID, viewer: ActionViewer, now: datetime
) -> Sequence[RankedItem]:  # fmt: skip
    extra = [
        *load_quote_reviews(session, company_id, viewer),
        *load_overdue_waits(session, company_id, viewer, now),
        *load_document_reviews(session, company_id, viewer),
    ]
    return [
        *load_approvals(session, company_id, viewer),
        *load_replies_needed(session, company_id, viewer),
        *(RankedItem(action, ts) for action, ts in extra),
    ]
