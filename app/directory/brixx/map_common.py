"""Shared pieces of the BRIXX directory mapper parts: counts, the per-company lock, change-only updates, end dates."""

from collections import Counter
from dataclasses import dataclass
from datetime import date
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.orm import Session


@dataclass(frozen=True)
class MapCounts:
    created: int = 0
    updated: int = 0
    unchanged: int = 0
    skipped: int = 0
    missing_table: bool = False

    @classmethod
    def missing(cls) -> "MapCounts":
        return cls(missing_table=True)

    @classmethod
    def tally(cls, outcomes: Counter[str]) -> "MapCounts":
        return cls(outcomes["created"], outcomes["updated"], outcomes["unchanged"], outcomes["skipped"])

    def as_dict(self) -> dict[str, int]:
        return {
            "created": self.created,
            "updated": self.updated,
            "unchanged": self.unchanged,
            "skipped": self.skipped,
            "missing_table": int(self.missing_table),
        }


def lock_company(session: Session, company_id: UUID) -> None:
    """Serialise mapper transactions per company (released at commit or rollback)."""
    session.execute(sa.select(sa.func.pg_advisory_xact_lock(sa.func.hashtextextended(f"brixx-map:{company_id}", 0))))


def changed(target: object, **values: object) -> bool:
    """Set the attributes that differ; True when anything changed (so an unchanged row is never rewritten)."""
    dirty = False
    for name, value in values.items():
        if getattr(target, name) != value:
            setattr(target, name, value)
            dirty = True
    return dirty


def ended_on(end: date | None, *, ended: bool, today: date) -> date | None:
    """`valid_to`: the source end date; an ended source row ends no later than today."""
    if not ended:
        return end
    return today if end is None or end > today else end
