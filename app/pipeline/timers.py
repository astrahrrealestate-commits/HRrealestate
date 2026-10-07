"""Due-work timers (invariant 2: long waits are DB rows, never sleeping workflows).

`schedule` is idempotent per (company, dedupe_key). `claim_due` takes due rows with `FOR UPDATE SKIP LOCKED` and a
lease, so concurrent sweeps never claim the same row and a crashed handler's row is reclaimed after the lease.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import Engine, and_, or_, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.db.enums import TimerStatus
from app.db.models import Timer

LEASE = timedelta(minutes=5)
MAX_ATTEMPTS = 5
CLAIM_BATCH = 100


@dataclass(frozen=True)
class ClaimedTimer:
    id: UUID
    company_id: UUID
    kind: str
    payload: dict[str, Any]
    attempts: int


def schedule(
    session: Session, company_id: UUID, kind: str, due_at: datetime, payload: dict[str, Any], *, dedupe_key: str
) -> UUID:
    """Insert a pending timer unless one with this dedupe key exists; returns the (existing) timer id."""
    session.execute(
        insert(Timer)
        .values(company_id=company_id, kind=kind, due_at=due_at, payload=payload, dedupe_key=dedupe_key)
        .on_conflict_do_nothing(index_elements=["company_id", "dedupe_key"])
    )
    return session.execute(
        select(Timer.id).where(Timer.company_id == company_id, Timer.dedupe_key == dedupe_key)
    ).scalar_one()  # inserted above or already present


def cancel(session: Session, company_id: UUID, dedupe_key: str) -> bool:
    result = session.execute(
        update(Timer)
        .where(
            Timer.company_id == company_id,
            Timer.dedupe_key == dedupe_key,
            Timer.status.in_([TimerStatus.pending, TimerStatus.running]),
        )
        .values(status=TimerStatus.cancelled)
    )
    return bool(result.rowcount)  # type: ignore[attr-defined]  # CursorResult of an UPDATE


def _claimable(now: datetime) -> Any:
    return or_(
        and_(Timer.status == TimerStatus.pending, Timer.due_at <= now),
        and_(Timer.status == TimerStatus.running, Timer.locked_until < now),
    )


def claim_due(engine: Engine, now: datetime, limit: int = CLAIM_BATCH) -> list[ClaimedTimer]:
    """Claim due (or lease-expired) timers. Rows that already used MAX_ATTEMPTS are marked failed instead."""
    with Session(engine) as session, session.begin():
        rows = session.scalars(
            select(Timer).where(_claimable(now)).order_by(Timer.due_at).limit(limit).with_for_update(skip_locked=True)
        ).all()
        claimed: list[ClaimedTimer] = []
        for row in rows:
            if row.attempts >= MAX_ATTEMPTS:
                row.status = TimerStatus.failed
                continue
            row.status, row.attempts, row.locked_until = TimerStatus.running, row.attempts + 1, now + LEASE
            claimed.append(ClaimedTimer(row.id, row.company_id, row.kind, dict(row.payload), row.attempts))
        return claimed


def finish(engine: Engine, timer_id: UUID, attempts: int, status: TimerStatus) -> None:
    """Mark a claimed timer done/failed, only if it is still this claim (a reclaimed row belongs to the newer run)."""
    with Session(engine) as session, session.begin():
        session.execute(
            update(Timer)
            .where(Timer.id == timer_id, Timer.attempts == attempts, Timer.status == TimerStatus.running)
            .values(status=status, locked_until=None)
        )
