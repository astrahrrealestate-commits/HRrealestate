"""Finance repository: agreed rate cards, decision-day price snapshots and the daily lookup count; quotes, lines and
reviews live in `app.finance.repo_quotes` and are re-exported here.

Every function takes `company_id` and filters or writes by it; rows it points at are checked to be the company's own.
Sessions are passed in; nothing here commits. Units are stored and compared normalised (`normalise_unit`).
"""

from collections.abc import Sequence
from datetime import date
from decimal import Decimal
from typing import Any, Literal
from uuid import UUID

from sqlalchemy import func, or_, select
from sqlalchemy.dialects.postgresql import distinct_on
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.contracts.finance import PriceBasis
from app.core.errors import NotFoundError
from app.core.ids import new_id
from app.core.property_terms import normalise_unit
from app.db.enums import PersonKind, RateSource
from app.db.models import ActionRow, Person, PriceSnapshot, VendorRate
from app.finance.repo_quotes import (
    NewQuoteLine,
    insert_quote,
    insert_quote_lines,
    insert_review,
    require_in_company,
)
from app.finance.stats import MarketStats

__all__ = [
    "NewQuoteLine",
    "current_rate",
    "insert_quote",
    "insert_quote_lines",
    "insert_review",
    "insert_snapshot",
    "is_contractor",
    "list_rates",
    "lookups_today",
    "remove_rate",
    "snapshot_for",
    "snapshots_for_case",
    "upsert_rate",
]

MAX_RATES = 500
_RATE_UPDATABLE = ("description", "unit", "amount", "currency", "valid_to", "source", "source_ref")


def current_rate(
    session: Session, company_id: UUID, person_id: UUID, item_key: str, unit: str, on: date
) -> VendorRate | None:
    """The vendor's rate for `item_key` per `unit` valid on `on` (latest `valid_from`); units compared normalised."""
    rows = session.scalars(
        select(VendorRate)
        .where(
            VendorRate.company_id == company_id,
            VendorRate.person_id == person_id,
            VendorRate.item_key == item_key,
            VendorRate.valid_from <= on,
            or_(VendorRate.valid_to.is_(None), VendorRate.valid_to >= on),
        )
        .order_by(VendorRate.valid_from.desc(), VendorRate.created_at.desc(), VendorRate.id.desc())
    )
    wanted = normalise_unit(unit)
    return next((rate for rate in rows if normalise_unit(rate.unit) == wanted), None)


def upsert_rate(
    session: Session,
    company_id: UUID,
    *,
    person_id: UUID,
    item_key: str,
    description: str,
    unit: str,
    amount: Decimal,
    currency: str,
    valid_from: date,
    source: RateSource,
    valid_to: date | None = None,
    source_ref: str | None = None,
) -> VendorRate:
    """Insert the rate, or replace the one with the same (person, item_key, valid_from); the person must be ours."""
    require_in_company(session, Person, company_id, person_id)
    values: dict[str, Any] = {
        "description": description, "unit": normalise_unit(unit), "amount": amount,
        "currency": currency.strip().upper(), "valid_to": valid_to, "source": source, "source_ref": source_ref,
    }  # fmt: skip
    insert = pg_insert(VendorRate).values(
        id=new_id(), company_id=company_id, person_id=person_id, item_key=item_key, valid_from=valid_from, **values
    )
    upsert = insert.on_conflict_do_update(
        index_elements=["company_id", "person_id", "item_key", "valid_from"],
        set_={name: insert.excluded[name] for name in _RATE_UPDATABLE},
    ).returning(VendorRate)
    return session.scalars(upsert, execution_options={"populate_existing": True}).one()


def is_contractor(session: Session, company_id: UUID, person_id: UUID) -> bool:
    """True when `person_id` is a contractor of this company (rates are only agreed with contractors)."""
    found = session.scalar(
        select(Person.id).where(
            Person.company_id == company_id, Person.id == person_id, Person.kind == PersonKind.contractor
        )
    )
    return found is not None


def list_rates(
    session: Session, company_id: UUID, *, person_id: UUID | None = None, limit: int = MAX_RATES
) -> list[VendorRate]:
    """The company's rate cards (closed ones too), by contractor and item, newest `valid_from` first."""
    stmt = select(VendorRate).where(VendorRate.company_id == company_id)
    if person_id is not None:
        stmt = stmt.where(VendorRate.person_id == person_id)
    order = (VendorRate.person_id, VendorRate.item_key, VendorRate.valid_from.desc(), VendorRate.id)
    return list(session.scalars(stmt.order_by(*order).limit(max(1, min(limit, MAX_RATES)))))


def remove_rate(
    session: Session, company_id: UUID, rate_id: UUID, *, today: date
) -> tuple[Literal["deleted", "closed"], date | None] | None:
    """Delete the company's rate, or close it (`valid_to` = `today`) when a price snapshot points at it: snapshots are
    immutable decision-day facts. Returns ("deleted", None) or ("closed", valid_to); None if it is not ours."""
    rate = session.scalar(select(VendorRate).where(VendorRate.company_id == company_id, VendorRate.id == rate_id))
    if rate is None:
        return None
    referenced = session.scalar(
        select(PriceSnapshot.id)
        .where(PriceSnapshot.company_id == company_id, PriceSnapshot.rate_card_id == rate_id)
        .limit(1)
    )
    if referenced is None:
        try:
            with session.begin_nested():
                session.delete(rate)
            return "deleted", None
        except IntegrityError:  # a snapshot started pointing at it since the check: close instead
            session.refresh(rate)
    if rate.valid_to is None or rate.valid_to > today:
        rate.valid_to = max(today, rate.valid_from)
        session.flush()
    return "closed", rate.valid_to


def snapshot_for(session: Session, company_id: UUID, case_id: UUID, item_key: str, on: date) -> PriceSnapshot | None:
    """The case's latest snapshot of `item_key` taken at or before `on` (None if only later ones exist)."""
    return session.scalars(
        select(PriceSnapshot)
        .where(
            PriceSnapshot.company_id == company_id,
            PriceSnapshot.case_id == case_id,
            PriceSnapshot.item_key == item_key,
            PriceSnapshot.as_of <= on,
        )
        .order_by(PriceSnapshot.as_of.desc(), PriceSnapshot.created_at.desc(), PriceSnapshot.id.desc())
        .limit(1)
    ).first()


def snapshots_for_case(session: Session, company_id: UUID, case_id: UUID, on: date) -> list[PriceSnapshot]:
    """Per item, the case's latest snapshot taken at or before `on`, ordered by item_key."""
    stmt = (
        select(PriceSnapshot)
        .where(PriceSnapshot.company_id == company_id, PriceSnapshot.case_id == case_id, PriceSnapshot.as_of <= on)
        .ext(distinct_on(PriceSnapshot.item_key))
        .order_by(
            PriceSnapshot.item_key, PriceSnapshot.as_of.desc(), PriceSnapshot.created_at.desc(), PriceSnapshot.id.desc()
        )
    )
    return list(session.scalars(stmt))


def insert_snapshot(
    session: Session,
    company_id: UUID,
    *,
    action_id: UUID,
    item_key: str,
    unit: str,
    as_of: date,
    stats: MarketStats,
    basis: PriceBasis,
    sources: Sequence[dict[str, str]],
    rate_card: VendorRate | None = None,
    snapshot_id: UUID | None = None,
) -> bool:
    """Store one item's decision-day prices (case from the action); False if (action, item_key) is already stored."""
    case_id = session.scalar(
        select(ActionRow.case_id).where(ActionRow.company_id == company_id, ActionRow.id == action_id)
    )
    if case_id is None:
        raise NotFoundError(f"action {action_id} not found in company")
    if rate_card is not None and rate_card.company_id != company_id:
        raise NotFoundError(f"rate {rate_card.id} not found in company")
    stmt = (
        pg_insert(PriceSnapshot)
        .values(
            id=snapshot_id or new_id(),
            company_id=company_id,
            case_id=case_id,
            action_id=action_id,
            item_key=item_key,
            unit=normalise_unit(unit),
            as_of=as_of,
            low=stats.low,
            avg=stats.avg,
            high=stats.high,
            sample_count=stats.n,
            basis=basis,
            sources=list(sources),
            rate_card_amount=rate_card.amount if rate_card else None,
            rate_card_id=rate_card.id if rate_card else None,
        )
        .on_conflict_do_nothing(index_elements=["company_id", "action_id", "item_key"])
        .returning(PriceSnapshot.id)
    )
    return session.scalar(stmt) is not None


def lookups_today(session: Session, company_id: UUID, today: date) -> int:
    """Snapshot item lookups the company used today (= its snapshot rows with `as_of` today), for the daily cap."""
    count = session.scalar(
        select(func.count(PriceSnapshot.id)).where(PriceSnapshot.company_id == company_id, PriceSnapshot.as_of == today)
    )
    return count or 0
