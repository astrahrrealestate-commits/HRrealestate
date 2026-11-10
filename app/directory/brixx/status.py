"""BRIXX sync status read model: last run, per-table health and staleness, from the state tables only.

Never calls BRIXX and never reads mirror rows. Every query filters by `company_id`.

Per-table `last_success_at` is derived, since the state row keeps no success timestamp: when the table's last run
finished it cleanly (`last_page == 0`, no `last_error`) it is that run's ORIGINAL start (every change before it was
fetched); otherwise (a newer run is mid-table or the last attempt failed) it falls back to the incremental watermark
`last_success_upd`, a lower bound. Tables without `UPDDATETIME` have no watermark, so they show null while a run is
mid-table or failing.
"""

from datetime import datetime, timedelta
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.orm import Session, aliased

from app.contracts.brixx import BrixxRun, BrixxRunStatus, BrixxStatus, BrixxTableStatus
from app.db.models.brixx import BrixxSyncRun, BrixxSyncTableState

STALE_AFTER_INTERVALS = 3


def is_stale(last_success: datetime | None, now: datetime, interval_minutes: int) -> bool:
    """True when no run succeeded within `STALE_AFTER_INTERVALS` sync intervals (or none ever did)."""
    if last_success is None:
        return True
    return now - last_success > timedelta(minutes=interval_minutes * STALE_AFTER_INTERVALS)


def table_last_success(
    *, last_page: int, last_error: str | None, run_started_at: datetime | None, watermark: datetime | None
) -> datetime | None:
    """When the mirror last had every change of this table (see the module docstring)."""
    if run_started_at is not None and last_page == 0 and last_error is None:
        return run_started_at
    return watermark


def lag_seconds(last_success: datetime | None, now: datetime) -> int | None:
    """Whole seconds since `last_success`; 0 when the worker's clock is ahead of ours."""
    if last_success is None:
        return None
    return max(0, int((now - last_success).total_seconds()))


def load_status(session: Session, company_id: UUID, *, now: datetime, interval_minutes: int) -> BrixxStatus:
    tables = _tables(session, company_id, now)
    return BrixxStatus(
        last_run=_last_run(session, company_id),
        tables=tables,
        total_rows=sum(t.row_count for t in tables),
        stale=is_stale(_last_success(session, company_id), now, interval_minutes),
    )


def _tables(session: Session, company_id: UUID, now: datetime) -> list[BrixxTableStatus]:
    run = aliased(BrixxSyncRun)
    rows = session.execute(
        sa.select(BrixxSyncTableState, run.started_at)
        .outerjoin(run, sa.and_(run.id == BrixxSyncTableState.last_run_id, run.company_id == company_id))
        .where(BrixxSyncTableState.company_id == company_id)
        .order_by(BrixxSyncTableState.table_name)
    ).all()
    out = []
    for state, run_started_at in rows:
        success = table_last_success(
            last_page=state.last_page,
            last_error=state.last_error,
            run_started_at=run_started_at,
            watermark=state.last_success_upd,
        )
        out.append(
            BrixxTableStatus(
                name=state.table_name,
                row_count=state.row_count,
                last_success_at=success,
                lag_seconds=lag_seconds(success, now),
                drifted=state.drifted,
                last_error=state.last_error,
            )
        )
    return out


def _last_run(session: Session, company_id: UUID) -> BrixxRun | None:
    found = session.scalars(
        sa.select(BrixxSyncRun)
        .where(BrixxSyncRun.company_id == company_id)
        .order_by(BrixxSyncRun.started_at.desc(), BrixxSyncRun.id.desc())
        .limit(1)
    ).one_or_none()
    if found is None:
        return None
    return BrixxRun(
        id=found.id,
        kind=found.kind,
        status=found.status,
        started_at=found.started_at,
        finished_at=found.finished_at,
        error=found.error,
    )


def _last_success(session: Session, company_id: UUID) -> datetime | None:
    return session.scalar(
        sa.select(sa.func.max(BrixxSyncRun.finished_at)).where(
            BrixxSyncRun.company_id == company_id, BrixxSyncRun.status == BrixxRunStatus.succeeded
        )
    )
