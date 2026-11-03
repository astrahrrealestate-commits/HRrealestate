"""`PRG_VHE` (rentable units) -> `units`, with the parent `PRG_OBJECT` (building) as label and address fallback.

`brixx_ref` is the VHE primary key. A unit ends when its VHE or its object is soft-deleted (reconcile or
`INDVERWIJDERD`); it reopens when BRIXX lists it again. Flushes; the caller commits.
"""

from collections import Counter
from collections.abc import Mapping
from datetime import date
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.orm import Session

from app.db.models import Unit
from app.directory.brixx import columns as col
from app.directory.brixx.map_common import MapCounts, changed, ended_on, lock_company

MAX_LABEL = 100
MAX_ADDRESS = 300


def unit_values(vhe: col.Row, building: col.Row | None, ref: int) -> dict[str, object]:
    """Label and address of one VHE: its own values first, then its object's, then a generated label."""
    label = col.pick_text(vhe, col.VHE_LABEL, MAX_LABEL) or col.pick_text(building, col.OBJECT_LABEL, MAX_LABEL)
    return {
        "label": label or f"VHE {ref}",
        "address": col.address(vhe, MAX_ADDRESS) or col.address(building, MAX_ADDRESS),
    }


def map_units(session: Session, company_id: UUID, today: date) -> MapCounts:
    lock_company(session, company_id)
    vhes = col.read_mirror(session, col.VHE, company_id)
    if vhes is None:
        return MapCounts.missing()
    buildings = {
        key: row
        for row in col.read_mirror(session, col.OBJECT, company_id) or []
        if (key := col.pick_int(row, (col.OBJECT_PK,))) is not None
    }
    existing = session.scalars(sa.select(Unit).where(Unit.company_id == company_id, Unit.brixx_ref.is_not(None)))
    units = {u.brixx_ref: u for u in existing if u.brixx_ref}
    outcomes = Counter(_map_one(session, company_id, today, row, buildings, units) for row in vhes)
    session.flush()
    return MapCounts.tally(outcomes)


def _map_one(
    session: Session,
    company_id: UUID,
    today: date,
    row: col.Row,
    buildings: Mapping[int, col.Row],
    units: dict[str, Unit],
) -> str:
    ref = col.pick_int(row, (col.VHE_PK,))
    if ref is None:
        return "skipped"
    object_id = col.pick_int(row, (col.OBJECT_PK,))
    building = buildings.get(object_id) if object_id is not None else None
    ended = col.is_ended(row) or col.is_ended(building)
    values = unit_values(row, building, ref)
    unit = units.get(str(ref))
    if unit is None:
        start = col.pick_date(row, col.CREATED) or today
        unit = Unit(company_id=company_id, brixx_ref=str(ref), valid_from=start, valid_to=today if ended else None)
        changed(unit, **values)
        session.add(unit)
        units[str(ref)] = unit
        return "created"
    valid_to = ended_on(unit.valid_to, ended=True, today=today) if ended else None
    return "updated" if changed(unit, **values, valid_to=valid_to) else "unchanged"
