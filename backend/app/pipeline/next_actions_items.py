"""Quote, wait and document loaders for category next actions (M13 T10). Every query filters by `company_id`."""

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Literal
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.context.sender_label import safe_name
from app.contracts import CaseState, Category, Urgency
from app.contracts.categories import current_category
from app.contracts.common import Contract
from app.db.enums import DocLinkKind, DocumentStatus, WaitStatus
from app.db.models import (
    AttachmentRow,
    Case,
    DocumentLink,
    DocumentRow,
    MessageRow,
    Person,
    QuoteReview,
    QuoteRow,
    WaitRow,
)
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
# Older than this, a document or flagged quote shows only while its case is open: a mailbox reload makes every row
# new, so the age is the mail's or the quote's own date.
DESK_DAYS = 30
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
    channel: str | None = None
    sender_name: str | None = None
    unit_label: str | None = None
    subject: str | None = None
    last_at: datetime | None = None
    waiting_side: Literal["owner", "third_party"] | None = None
    waiting_days: int | None = None
    obligation: str | None = None
    has_draft: bool = False
    overdue_days: int = 0
    chase_count: int = 0
    wait_status: Literal["waiting", "chased", "escalated", "promise"] | None = None
    wait_id: UUID | None = None


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


def _to_local_dt(stamp: datetime | date | str | None, tz_name: str = "Europe/Amsterdam") -> datetime | None:
    if stamp is None:
        return None
    if isinstance(stamp, str):
        try:
            stamp = datetime.fromisoformat(stamp)
        except ValueError:
            return None
    if isinstance(stamp, date) and not isinstance(stamp, datetime):
        return datetime(stamp.year, stamp.month, stamp.day, tzinfo=ZoneInfo(tz_name))
    return as_utc(stamp).astimezone(ZoneInfo(tz_name))


def period_key(stamp: datetime | date | str | None, tz_name: str = "Europe/Amsterdam") -> str | None:
    """Return `YYYY-MM` in company timezone for period pickers, or None if no date."""
    local = _to_local_dt(stamp, tz_name)
    return f"{local.year:04d}-{local.month:02d}" if local is not None else None


def matches_period(
    stamp: datetime | date | str | None,
    period: str,
    ref: datetime,
    tz_name: str = "Europe/Amsterdam",
) -> bool:
    """True when `stamp` falls inside `all`, `this_week` (last 7d), `YYYY-MM`, or `YYYY`."""
    p = (period or "all").strip().lower()
    if not p or p == "all":
        return True
    local = _to_local_dt(stamp, tz_name)
    if local is None:
        return False
    if p == "this_week":
        return local >= as_utc(ref).astimezone(ZoneInfo(tz_name)) - timedelta(days=7)
    if len(p) == 7 and p[4] == "-":
        return f"{local.year:04d}-{local.month:02d}" == p
    if len(p) == 4 and p.isdigit():
        return f"{local.year:04d}" == p
    return True


def _older(when: datetime | date | None) -> bool:
    """Past the desk window; an item with no date of its own stays."""
    if when is None:
        return False
    cutoff = datetime.now(UTC) - timedelta(days=DESK_DAYS)
    return (as_utc(when) if isinstance(when, datetime) else when) < (
        cutoff if isinstance(when, datetime) else cutoff.date()
    )


def one_line(text: str | None, limit: int = 160) -> str:
    return " ".join((text or "").split())[:limit]


def load_quote_reviews(session: Session, company_id: UUID, viewer: ActionViewer) -> list[tuple[NextAction, datetime]]:
    """Flagged quotes; they name prices and overcharges, so only a profile with the money section sees them."""
    if not viewer.money:
        return []
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
        unlinked: Case | None = case  # an outer join: a quote without a case has none
        if unlinked is None and _older(quote.quote_date):
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
                        last_at=as_utc(review.created_at),
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
        .where(
            WaitRow.company_id == company_id,
            WaitRow.status == WaitStatus.waiting,
            WaitRow.expected_by <= now,
            Case.state.in_(OPEN_STATES),
        )
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
                    last_at=as_utc(wait.expected_by),
                ),
                as_utc(wait.expected_by),
            )
        )
    return out


def load_document_reviews(
    session: Session, company_id: UUID, viewer: ActionViewer
) -> list[tuple[NextAction, datetime]]:  # fmt: skip
    found = session.execute(
        select(DocumentRow, MessageRow.sent_at)
        .outerjoin(
            AttachmentRow, (AttachmentRow.id == DocumentRow.attachment_id) & (AttachmentRow.company_id == company_id)
        )
        .outerjoin(MessageRow, (MessageRow.id == AttachmentRow.message_id) & (MessageRow.company_id == company_id))
        .where(DocumentRow.company_id == company_id, DocumentRow.status == DocumentStatus.review)
    ).all()
    if not found:
        return []
    docs = [doc for doc, _ in found]
    sent = {doc.id: sent_at for doc, sent_at in found}
    case_links = session.execute(
        select(DocumentLink.document_id, Case.id, Case.category, Case.urgency, Case.state)
        .join(Case, (Case.id == DocumentLink.ref_id) & (Case.company_id == company_id))
        .where(
            DocumentLink.company_id == company_id,
            DocumentLink.kind == DocLinkKind.case,
            DocumentLink.document_id.in_([d.id for d in docs]),
        )
    ).all()
    by_doc = {doc_id: (cid, cat, urg) for doc_id, cid, cat, urg, state in case_links if state in OPEN_STATES}
    out: list[tuple[NextAction, datetime]] = []
    for doc in docs:
        linked = by_doc.get(doc.id)
        if linked is None and _older(sent[doc.id] or doc.created_at):
            continue
        cat = current_category(linked[1].value) if linked else Category.administration
        if cat is Category.spam:
            continue
        title = (
            f"Review {doc.doc_type}: {strip_risky(doc.title)}" if viewer.inbox else f"Review {doc.doc_type} document"
        )
        doc_ts = as_utc(sent[doc.id] or doc.created_at)
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
                    last_at=doc_ts,
                ),
                doc_ts,
            )
        )
    return out
