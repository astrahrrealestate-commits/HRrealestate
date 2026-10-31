"""Other contractors' current agreed rates as market observations (never the quoting vendor, never another company)."""

from collections.abc import Callable
from datetime import date
from uuid import UUID

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.channels.prices.ports import PriceObservation
from app.db.models import Person, VendorRate


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
                VendorRate.valid_from <= as_of,
                or_(VendorRate.valid_to.is_(None), VendorRate.valid_to >= as_of),
            )
            .order_by(VendorRate.amount, Person.display_name)
        )
        if self._exclude is not None:
            stmt = stmt.where(VendorRate.person_id != self._exclude)
        with self._session_factory() as session:
            rows = session.execute(stmt).all()
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
