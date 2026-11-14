"""Finance repository, read half for the dashboard: quote pages, one quote with its reviews, review counts.

Every query filters by `company_id`; the vendor name is joined by (id, company_id) too. Sessions are passed in.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from sqlalchemy import func, select, tuple_
from sqlalchemy.dialects.postgresql import distinct_on
from sqlalchemy.orm import Session

from app.db.models import Person, QuoteLineRow, QuoteReview, QuoteRow

MAX_QUOTE_PAGE = 100
Cursor = tuple[datetime, UUID]


@dataclass(frozen=True)
class QuoteListRow:
    quote: QuoteRow
    vendor_name: str | None
    latest: QuoteReview | None


@dataclass(frozen=True)
class QuoteDetail:
    quote: QuoteRow
    vendor_name: str | None
    lines: Sequence[QuoteLineRow]
    latest: QuoteReview | None
    history: Sequence[tuple[UUID, str, datetime]]  # (review id, verdict, created_at), newest first


def _latest_reviews(session: Session, company_id: UUID, quote_ids: Sequence[UUID]) -> dict[UUID, QuoteReview]:
    stmt = (
        select(QuoteReview)
        .where(QuoteReview.company_id == company_id, QuoteReview.quote_id.in_(quote_ids))
        .ext(distinct_on(QuoteReview.quote_id))
        .order_by(QuoteReview.quote_id, QuoteReview.created_at.desc(), QuoteReview.id.desc())
    )
    return {review.quote_id: review for review in session.scalars(stmt)}


def list_quotes(
    session: Session,
    company_id: UUID,
    *,
    case_id: UUID | None = None,
    person_id: UUID | None = None,
    before: Cursor | None = None,
    limit: int = 50,
) -> list[QuoteListRow]:
    """The company's quotes newest first, each with its latest review; `before` is the (created_at, id) of the last
    row of the previous page."""
    stmt = (
        select(QuoteRow, Person.display_name)
        .outerjoin(Person, (Person.id == QuoteRow.person_id) & (Person.company_id == company_id))
        .where(QuoteRow.company_id == company_id)
    )
    if case_id is not None:
        stmt = stmt.where(QuoteRow.case_id == case_id)
    if person_id is not None:
        stmt = stmt.where(QuoteRow.person_id == person_id)
    if before is not None:
        stmt = stmt.where(tuple_(QuoteRow.created_at, QuoteRow.id) < tuple_(*before))
    capped = max(1, min(limit, MAX_QUOTE_PAGE))
    rows = session.execute(stmt.order_by(QuoteRow.created_at.desc(), QuoteRow.id.desc()).limit(capped)).all()
    latest = _latest_reviews(session, company_id, [r[0].id for r in rows]) if rows else {}
    return [QuoteListRow(quote, name, latest.get(quote.id)) for quote, name in rows]


def get_quote(session: Session, company_id: UUID, quote_id: UUID) -> QuoteDetail | None:
    """One of the company's quotes with its lines, latest review and the (id, verdict, time) history; else None."""
    row = session.execute(
        select(QuoteRow, Person.display_name)
        .outerjoin(Person, (Person.id == QuoteRow.person_id) & (Person.company_id == company_id))
        .where(QuoteRow.company_id == company_id, QuoteRow.id == quote_id)
    ).first()
    if row is None:
        return None
    lines = session.scalars(
        select(QuoteLineRow)
        .where(QuoteLineRow.company_id == company_id, QuoteLineRow.quote_id == quote_id)
        .order_by(QuoteLineRow.position, QuoteLineRow.id)
    ).all()
    history = session.execute(
        select(QuoteReview.id, QuoteReview.verdict, QuoteReview.created_at)
        .where(QuoteReview.company_id == company_id, QuoteReview.quote_id == quote_id)
        .order_by(QuoteReview.created_at.desc(), QuoteReview.id.desc())
    ).all()
    latest = _latest_reviews(session, company_id, [quote_id]).get(quote_id)
    return QuoteDetail(row[0], row[1], lines, latest, [(h.id, h.verdict.value, h.created_at) for h in history])


def review_count(session: Session, company_id: UUID, quote_id: UUID) -> int:
    """Reviews stored for the company's quote: the `n` of its next recheck."""
    count = session.scalar(
        select(func.count(QuoteReview.id)).where(QuoteReview.company_id == company_id, QuoteReview.quote_id == quote_id)
    )
    return count or 0
