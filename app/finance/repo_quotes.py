"""Finance repository, quote half: quotes, their lines and their reviews (re-exported by `app.finance.repo`).

Every function takes `company_id`, writes it and checks that every row it points at belongs to that company (the FKs
do not: `CompanyScoped`). Sessions are passed in; nothing here commits.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.contracts.finance import SnapshotBasis, Verdict
from app.core.errors import NotFoundError
from app.core.ids import new_id
from app.core.property_terms import normalise_unit
from app.db.base import CompanyScoped
from app.db.enums import QuoteSource, QuoteStatus
from app.db.models import Case, DocumentRow, MessageRow, Person, QuoteLineRow, QuoteReview, QuoteRow

_SOURCE_TABLES: dict[QuoteSource, type[CompanyScoped]] = {
    QuoteSource.message: MessageRow,
    QuoteSource.document: DocumentRow,
}


@dataclass(frozen=True)
class NewQuoteLine:
    position: int
    description: str
    item_key: str
    quantity: Decimal
    unit: str
    amount: Decimal
    unit_price: Decimal | None = None
    vat_included: bool | None = None


def require_in_company(session: Session, model: type[CompanyScoped], company_id: UUID, row_id: UUID) -> None:
    """Raise NotFoundError unless `row_id` is a `model` row of this company."""
    found = session.scalar(select(model.id).where(model.company_id == company_id, model.id == row_id))
    if found is None:
        raise NotFoundError(f"{model.__name__} {row_id} not found in company")


def insert_quote(
    session: Session,
    company_id: UUID,
    *,
    source: QuoteSource,
    source_id: UUID,
    quote_date: date,
    currency: str,
    case_id: UUID | None = None,
    person_id: UUID | None = None,
    work_date: date | None = None,
    total: Decimal | None = None,
    status: QuoteStatus = QuoteStatus.received,
) -> UUID | None:
    """Insert a quote once per (company, source, source_id); None when it is already stored."""
    require_in_company(session, _SOURCE_TABLES[source], company_id, source_id)
    if case_id is not None:
        require_in_company(session, Case, company_id, case_id)
    if person_id is not None:
        require_in_company(session, Person, company_id, person_id)
    stmt = (
        pg_insert(QuoteRow)
        .values(
            id=new_id(),
            company_id=company_id,
            source=source,
            source_id=source_id,
            quote_date=quote_date,
            currency=currency.strip().upper(),
            case_id=case_id,
            person_id=person_id,
            work_date=work_date,
            total=total,
            status=status,
        )
        .on_conflict_do_nothing(index_elements=["company_id", "source", "source_id"])
        .returning(QuoteRow.id)
    )
    return session.scalar(stmt)


def insert_quote_lines(
    session: Session, company_id: UUID, *, quote_id: UUID, lines: Sequence[NewQuoteLine]
) -> list[UUID]:
    """Insert the lines of one of this company's quotes (units stored normalised); returns their ids in order."""
    require_in_company(session, QuoteRow, company_id, quote_id)
    rows = [
        QuoteLineRow(
            id=new_id(),
            company_id=company_id,
            quote_id=quote_id,
            position=ln.position,
            description=ln.description,
            item_key=ln.item_key,
            quantity=ln.quantity,
            unit=normalise_unit(ln.unit),
            unit_price=ln.unit_price,
            amount=ln.amount,
            vat_included=ln.vat_included,
        )
        for ln in lines
    ]
    session.add_all(rows)
    session.flush()
    return [row.id for row in rows]


def insert_review(
    session: Session,
    company_id: UUID,
    *,
    quote_id: UUID,
    snapshot_basis: SnapshotBasis,
    verdict: Verdict,
    overcharge: Decimal,
    late_days: int,
    report: dict[str, Any],
) -> UUID:
    """Append a review of one of this company's quotes (append-only: a recheck adds a row)."""
    require_in_company(session, QuoteRow, company_id, quote_id)
    row = QuoteReview(
        id=new_id(), company_id=company_id, quote_id=quote_id, snapshot_basis=snapshot_basis, verdict=verdict,
        overcharge=overcharge, late_days=late_days, report=report,
    )  # fmt: skip
    session.add(row)
    session.flush()
    return row.id
