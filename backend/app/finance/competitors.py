"""Other contractors' current agreed rates as market observations (never the quoting vendor, never another company).

Units are matched by `normalise_unit` (a rate stored as `uur` or `Hour ` is an `hour` rate), after the query: per
vendor, the newest version valid on `as_of` in the wanted unit is the observation.
"""

from collections.abc import Callable
from datetime import date
from uuid import UUID

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.channels.prices.ports import PriceObservation
from app.core.property_terms import normalise_unit
from app.db.models import Person, VendorRate
from app.finance.review_types import REFERENCE_CURRENCY


class CompetitorRatesSource:
    def __init__(
        self, session_factory: Callable[[], Session], company_id: UUID, exclude_person_id: UUID | None
    ) -> None:
        self._session_factory = session_factory
        self._company_id = company_id
        self._exclude = exclude_person_id

    def _rates(self, item_key: str, as_of: date) -> list[tuple[VendorRate, str]]:
        """Valid EUR rates for the item, each vendor's newest version first."""
        stmt = (
            select(VendorRate, Person.display_name)
            .join(Person, (Person.id == VendorRate.person_id) & (Person.company_id == VendorRate.company_id))
            .where(
                VendorRate.company_id == self._company_id,
                VendorRate.item_key == item_key,
                VendorRate.currency == REFERENCE_CURRENCY,
                VendorRate.valid_from <= as_of,
                or_(VendorRate.valid_to.is_(None), VendorRate.valid_to >= as_of),
            )
            .order_by(VendorRate.person_id, VendorRate.valid_from.desc(), VendorRate.created_at.desc())
        )
        if self._exclude is not None:
            stmt = stmt.where(VendorRate.person_id != self._exclude)
        with self._session_factory() as session:
            return [(rate, name) for rate, name in session.execute(stmt).all()]

    def lookup(self, item_key: str, unit: str, as_of: date) -> list[PriceObservation]:
        wanted = normalise_unit(unit)
        newest: dict[UUID, tuple[VendorRate, str]] = {}
        for rate, name in self._rates(item_key, as_of):
            if normalise_unit(rate.unit) == wanted:
                newest.setdefault(rate.person_id, (rate, name))  # one rate per vendor
        rows = sorted(newest.values(), key=lambda r: (r[0].amount, r[1]))
        return [
            PriceObservation(
                amount=rate.amount,
                unit=wanted,
                vat_included=False,
                source=f"competitor:{name}",
                url=None,
                observed_on=as_of,
            )
            for rate, name in rows
        ]
