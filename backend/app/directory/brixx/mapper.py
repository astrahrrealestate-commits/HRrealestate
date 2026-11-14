"""BRIXX directory mapper (Phase D): the raw mirror fills `people`, `channel_identities`, `units`, `leases`.

Reads only the mirror (never the API), always for one company. Each part (`map_people`, `map_units`, `map_leases`)
runs in the caller's transaction under a per-company advisory lock, so two runs (an incremental and a reconcile)
never map concurrently; it flushes and the caller commits. Idempotent: `brixx_ref` is unique per company on each
table, so a second run with an unchanged mirror creates and changes nothing. Order matters: people, then units, then
leases (which link both). Only counts are logged, never names or contact data.
"""

from datetime import date
from uuid import UUID

from sqlalchemy.orm import Session

from app.directory.brixx.leases import map_leases
from app.directory.brixx.map_common import MapCounts
from app.directory.brixx.people import map_people
from app.directory.brixx.units import map_units

__all__ = ["MapCounts", "map_directory", "map_leases", "map_people", "map_units"]


def map_directory(session: Session, company_id: UUID, today: date) -> dict[str, MapCounts]:
    """All three parts in order, in the caller's transaction (the workflow runs them as separate steps)."""
    return {
        "people": map_people(session, company_id, today),
        "units": map_units(session, company_id, today),
        "leases": map_leases(session, company_id, today),
    }
