"""Other contractors' current agreed rates as market observations (never the quoting vendor, never another company)."""

from collections.abc import Callable
from datetime import date
from uuid import UUID

from sqlalchemy import or_, select
from sqlalchemy.dialects.postgresql import distinct_on
from sqlalchemy.orm import Session

from app.channels.prices.ports import PriceObservation
from app.db.models import Person, VendorRate
from app.finance.review_types import REFERENCE_CURRENCY


class CompetitorRatesSource:
    def __init__(
        self, session_factory: Callable[[], Session], company_id: UUID, exclude_person_id: UUID | None
    ) -> None:
        self._session_factory = session_factory
        self._company_id = company_id
        self._exclude = exclude_person_id

    def lookup(self, item_key: str, unit: str, as_of: date) -> list[PriceObservation]:
        stmt = (
            select(VendorRate, Person.display_name)
            .join(Person, (Person.id == VendorRate.person_id) & (Person.company_id == VendorRate.company_id))
            .where(
                VendorRate.company_id == self._company_id,
                VendorRate.item_key == item_key,
                VendorRate.unit == unit,
                VendorRate.currency == REFERENCE_CURRENCY,
                VendorRate.valid_from <= as_of,
                or_(VendorRate.valid_to.is_(None), VendorRate.valid_to >= as_of),
            )
            .ext(distinct_on(VendorRate.person_id))  # one rate per vendor: the newest version valid on as_of
            .order_by(VendorRate.person_id, VendorRate.valid_from.desc())
        )
        if self._exclude is not None:
            stmt = stmt.where(VendorRate.person_id != self._exclude)
        with self._session_factory() as session:
            rows = sorted(session.execute(stmt).all(), key=lambda r: (r[0].amount, r[1]))
        return [
            PriceObservation(
                amount=rate.amount,
                unit=rate.unit,
                vat_included=False,
                source=f"competitor:{name}",
                url=None,
                observed_on=as_of,
            )
            for rate, name in rows
        ]
