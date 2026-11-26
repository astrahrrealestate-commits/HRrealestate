"""Quote, wait and document loaders for category next actions (M13 T10). Every query filters by `company_id`."""

from datetime import UTC, datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.context.sender_label import safe_name
from app.contracts import CaseState, Category, Urgency
from app.contracts.categories import current_category
from app.contracts.common import Contract
from app.db.enums import DocLinkKind, DocumentStatus, WaitStatus
from app.db.models import Case, DocumentLink, DocumentRow, Person, QuoteReview, QuoteRow, WaitRow
from app.pipeline.document_qa import strip_risky

ActionKind = Literal[
    "approve_draft",
    "reply_needed",
    "quote_review",
    "overdue_wait",
    "document_review",
    "brixx_ticket",
    "rent_arrears",
    "lease_ending",
]
OPEN_STATES = (CaseState.open, CaseState.waiting_on_owner, CaseState.waiting_on_third_party)
FLAGGED_VERDICTS = ("above_market", "well_above_market", "above_agreed")


class NextAction(Contract):
    id: str
    category: Category
    kind: ActionKind
    title: str
    why: str
    urgency: Urgency
    due_at: datetime | None
    case_id: UUID | None
    approval_id: UUID | None
    prepared: str | None
    target_url: str


class ActionViewer:
    def __init__(self, *, money: bool, inbox: bool) -> None:
        self.money = money
        self.inbox = inbox

    def party(self, name: str | None, fallback: str = "Contact") -> str:
        raw = (name or "").strip()
        if not raw:
            return fallback
        return raw if self.inbox else safe_name(raw)


def as_utc(dt: datetime) -> datetime:
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=UTC)


def one_line(text: str | None, limit: int = 160) -> str:
    return " ".join((text or "").split())[:limit]


def load_quote_reviews(session: Session, company_id: UUID, viewer: ActionViewer) -> list[tuple[NextAction, datetime]]:
    rows = session.execute(
        select(QuoteReview, QuoteRow, Case, Person.display_name)
        .join(QuoteRow, (QuoteRow.id == QuoteReview.quote_id) & (QuoteRow.company_id == company_id))
        .outerjoin(Case, (Case.id == QuoteRow.case_id) & (Case.company_id == company_id))
        .outerjoin(Person, (Person.id == QuoteRow.person_id) & (Person.company_id == company_id))
        .where(QuoteReview.company_id == company_id)
        .order_by(QuoteReview.quote_id, QuoteReview.created_at.desc(), QuoteReview.id.desc())
    ).all()
    seen_quotes: set[UUID] = set()
    out: list[tuple[NextAction, datetime]] = []
    for review, quote, case, vendor_name in rows:
        if quote.id in seen_quotes:
            continue
        seen_quotes.add(quote.id)
        if review.verdict.value not in FLAGGED_VERDICTS or (case is not None and case.state not in OPEN_STATES):
            continue
        vendor = viewer.party(vendor_name, "Vendor")
        over = f"€{Decimal(review.overcharge):,.2f}" if review.overcharge else "€0.00"
        verdict = review.verdict.value.replace("_", " ")
        urgency = Urgency.high if review.verdict.value == "well_above_market" else Urgency.normal
        cats = [current_category(case.category.value)] if case is not None else []
        if Category.finance not in cats:
            cats.append(Category.finance)
        for cat in cats:
            if cat is Category.spam:
                continue
            out.append(
                (
                    NextAction(
                        id=f"quote:{review.id}:{cat.value}",
                        category=cat,
                        kind="quote_review",
                        title=f"Counter {vendor}'s quote",
                        why=f"{verdict} · overcharge {over}",
                        urgency=urgency,
                        due_at=None,
                        case_id=case.id if case is not None else None,
                        approval_id=None,
                        prepared=f"{verdict} ({over} overcharge)",
                        target_url=f"/inbox?thread={case.id}" if case is not None else "/money",
                    ),
                    as_utc(review.created_at),
                )
            )
    return out


def load_overdue_waits(
    session: Session, company_id: UUID, viewer: ActionViewer, now: datetime
) -> list[tuple[NextAction, datetime]]:  # fmt: skip
    rows = session.execute(
        select(WaitRow, Case, Person.display_name)
        .join(Case, (Case.id == WaitRow.case_id) & (Case.company_id == company_id))
        .outerjoin(Person, (Person.id == WaitRow.party_person_id) & (Person.company_id == company_id))
        .where(WaitRow.company_id == company_id, WaitRow.status == WaitStatus.waiting, WaitRow.expected_by <= now)
        .order_by(WaitRow.expected_by.asc())
    ).all()
    out: list[tuple[NextAction, datetime]] = []
    for wait, case, name in rows:
        cat = current_category(case.category.value)
        if cat is Category.spam:
            continue
        days = max(0, (now - as_utc(wait.expected_by)).days)
        party = viewer.party(name)
        why = (one_line(wait.about) if viewer.inbox else "") or f"Waiting {days} day{'s' if days != 1 else ''}"
        out.append(
            (
                NextAction(
                    id=f"wait:{wait.id}",
                    category=cat,
                    kind="overdue_wait",
                    title=f"Follow up with {party}",
                    why=why,
                    urgency=case.urgency,
                    due_at=as_utc(wait.expected_by),
                    case_id=case.id,
                    approval_id=None,
                    prepared=None,
                    target_url=f"/inbox?thread={case.id}",
                ),
                as_utc(wait.expected_by),
            )
        )
    return out


def load_document_reviews(
    session: Session, company_id: UUID, viewer: ActionViewer
) -> list[tuple[NextAction, datetime]]:  # fmt: skip
    docs = list(
        session.scalars(
            select(DocumentRow).where(DocumentRow.company_id == company_id, DocumentRow.status == DocumentStatus.review)
        ).all()
    )
    if not docs:
        return []
    case_links = session.execute(
        select(DocumentLink.document_id, Case.id, Case.category, Case.urgency)
        .join(Case, (Case.id == DocumentLink.ref_id) & (Case.company_id == company_id))
        .where(
            DocumentLink.company_id == company_id,
            DocumentLink.kind == DocLinkKind.case,
            DocumentLink.document_id.in_([d.id for d in docs]),
        )
    ).all()
    by_doc = {doc_id: (cid, cat, urg) for doc_id, cid, cat, urg in case_links}
    out: list[tuple[NextAction, datetime]] = []
    for doc in docs:
        linked = by_doc.get(doc.id)
        cat = current_category(linked[1].value) if linked else Category.administration
        if cat is Category.spam:
            continue
        title = (
            f"Review {doc.doc_type}: {strip_risky(doc.title)}" if viewer.inbox else f"Review {doc.doc_type} document"
        )
        out.append(
            (
                NextAction(
                    id=f"doc:{doc.id}",
                    category=cat,
                    kind="document_review",
                    title=title[:140],
                    why="Document needs owner review",
                    urgency=linked[2] if linked else Urgency.normal,
                    due_at=None,
                    case_id=linked[0] if linked else None,
                    approval_id=None,
                    prepared=None,
                    target_url="/inbox" if linked is None else f"/inbox?thread={linked[0]}",
                ),
                as_utc(doc.created_at),
            )
        )
    return out
