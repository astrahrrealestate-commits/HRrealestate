"""Facts about units and contracts that BRIXX knows and the directory tables do not: living area, deposit, rent.

Read from the mirror at request time for one company. Rent is the sum of a contract's current monthly payment lines
(`FIN_BETAALREGEL`) whose component (`TYP_HUURCOMPONENT.BENAMING`) is a rent ("Huur woonruimte", "Huur
parkeerplaats"); service costs, utilities, furnishing and the deposit line are not rent. Deposit is the contract's
`WAARBORGSOM`; living area the unit's `VVO` (else `BVO`). Zero or missing means unknown: nothing is invented.
"""

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from uuid import UUID

from sqlalchemy.orm import Session

from app.directory.brixx import columns as col

PAYMENTS, COMPONENTS = "fin_betaalregel", "typ_huurcomponent"
COMPONENT_PK = "typ_huurcomponentid"
AREA = ("vvo", "bvo")
DEPOSIT = ("waarborgsom",)
AMOUNT = ("bedragex",)
TERM_MONTHS = ("dm_bedragextermijnmnd",)


@dataclass(frozen=True)
class UnitFacts:
    area_sqm: dict[str, int] = field(default_factory=dict)  # unit brixx_ref -> m2
    deposit_eur: dict[int, float] = field(default_factory=dict)  # contract id -> EUR
    rent_eur: dict[int, float] = field(default_factory=dict)  # contract id -> EUR per month

    def for_lease(self, lease_ref: str | None) -> tuple[float | None, float | None]:
        """(monthly rent, deposit) of the contract a BRIXX lease ref `"<contractid>:<linkid>"` names."""
        contract = col.as_int(lease_ref.split(":", 1)[0]) if lease_ref else None
        if contract is None:
            return None, None
        return self.rent_eur.get(contract), self.deposit_eur.get(contract)


def _positive(value: object) -> Decimal | None:
    if isinstance(value, Decimal | int | float) and not isinstance(value, bool) and value > 0:
        return Decimal(str(value))
    return None


def _rent_components(session: Session, company_id: UUID) -> set[int]:
    rows = col.read_mirror(session, COMPONENTS, company_id) or []
    names = {col.pick_int(r, (COMPONENT_PK,)): str(col.pick(r, ("benaming", "omschrijving")) or "") for r in rows}
    return {key for key, name in names.items() if key is not None and name.lower().startswith("huur")}


def _monthly(row: col.Row, today: date) -> Decimal | None:
    start, end = col.pick_date(row, col.START), col.pick_date(row, col.END)
    if col.is_ended(row) or (start is not None and start > today) or (end is not None and end < today):
        return None
    term = col.as_int(col.pick(row, TERM_MONTHS))
    amount = _positive(col.pick(row, AMOUNT))
    if amount is None:
        return None
    return amount / Decimal(term) if term is not None and term > 1 else amount


def unit_facts(session: Session, company_id: UUID, today: date) -> UnitFacts:
    area = {
        str(ref): int(value)
        for row in col.read_mirror(session, col.VHE, company_id) or []
        if (ref := col.pick_int(row, (col.VHE_PK,))) is not None and (value := _positive(col.pick(row, AREA)))
    }
    deposit = {
        key: float(value)
        for row in col.read_mirror(session, col.CONTRACT, company_id) or []
        if (key := col.pick_int(row, (col.CONTRACT_PK,))) is not None and (value := _positive(col.pick(row, DEPOSIT)))
    }
    rent_kinds = _rent_components(session, company_id)
    rent: dict[int, Decimal] = defaultdict(Decimal)
    for row in col.read_mirror(session, PAYMENTS, company_id) or []:
        contract = col.pick_int(row, (col.CONTRACT_PK,))
        if contract is None or col.pick_int(row, (COMPONENT_PK,)) not in rent_kinds:
            continue
        if (monthly := _monthly(row, today)) is not None:
            rent[contract] += monthly
    return UnitFacts(area, deposit, {key: float(round(value, 2)) for key, value in rent.items()})
