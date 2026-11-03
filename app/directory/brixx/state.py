"""Per-table sync bookkeeping: resume point, incremental watermark and last error.

Run versus resume: `last_run_id` names the run that owns `last_page`. A rerun or DBOS retry of the same run id with
`last_page > 0` resumes at `last_page + 1`; any other run id starts at page 1 and resets the page counters.
`mark_success` zeroes `last_page`, so a finished table never "resumes". Nothing here commits: the caller owns the
transaction. Errors keep only a class name, the table and the page (messages can carry URLs or row values).
"""

from datetime import datetime
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import Session

from app.core.errors import BrixxError, StaleRunError
from app.db.models.brixx import BrixxSyncRun, BrixxSyncTableState


def get_or_create_table_state(session: Session, company_id: UUID, table: str) -> BrixxSyncTableState:
    """The state row for (company, table); concurrent creators converge on one row via the unique constraint."""
    found = _select(session, company_id, table)
    if found is not None:
        return found
    session.execute(
        postgresql.insert(BrixxSyncTableState)
        .values(company_id=company_id, table_name=table)
        .on_conflict_do_nothing(index_elements=["company_id", "table_name"])
    )
    created = _select(session, company_id, table)
    if created is None:
        raise BrixxError("BRIXX table state could not be created")
    return created


def _select(session: Session, company_id: UUID, table: str) -> BrixxSyncTableState | None:
    return session.scalars(
        sa.select(BrixxSyncTableState).where(
            BrixxSyncTableState.company_id == company_id, BrixxSyncTableState.table_name == table
        )
    ).one_or_none()


def begin_table_run(session: Session, state: BrixxSyncTableState, run_id: UUID) -> int:
    """First page to fetch for `run_id`: `last_page + 1` when this same run was interrupted, otherwise 1.

    Locks the state row (`FOR UPDATE`) until the caller commits. Taking over from another run resets the page
    counters, which makes that run's later `record_page`/`mark_success` calls raise `StaleRunError`. The run must
    exist for the state's own company.
    """
    _lock(session, state)
    known = session.scalar(
        sa.select(BrixxSyncRun.id).where(BrixxSyncRun.id == run_id, BrixxSyncRun.company_id == state.company_id)
    )
    if known is None:
        raise BrixxError(f"unknown BRIXX sync run for table {state.table_name!r}")
    if state.last_run_id == run_id and state.last_page > 0:
        return state.last_page + 1
    state.last_run_id = run_id
    state.last_page = 0
    state.row_count = 0
    session.flush()
    return 1


def record_page(session: Session, state: BrixxSyncTableState, page: int, written: int, run_id: UUID) -> None:
    """Mark `page` fully committed by `run_id`. Locks the state row; raises `StaleRunError` unless this run owns it.

    Pages must arrive in order: `last_page + 1` (page 1 when `last_page` is 0). The page just recorded (`last_page`)
    is accepted again as an idempotent replay (a DBOS step retried after its commit) and is not counted twice.
    """
    _lock(session, state)
    _require_owner(state, run_id)
    if page not in (state.last_page, state.last_page + 1) or page < 1:
        raise StaleRunError(f"BRIXX table {state.table_name!r} expected page {state.last_page + 1}, got {page}")
    if page > state.last_page:
        state.last_page = page
        state.row_count += written
    state.last_error = None
    session.flush()


def mark_success(
    session: Session, state: BrixxSyncTableState, upd: datetime | None, started_at: datetime, run_id: UUID
) -> None:
    """Finish the table: advance the watermark and clear the resume point. Call only after the last page.

    `started_at` must be the run's ORIGINAL start (not a retry's), both datetimes must be timezone-aware, and
    `run_id` must still own the table (else `StaleRunError`). The watermark never moves backwards and is capped at
    `started_at` so a future-dated row cannot skip later changes; `upd=None` leaves it as it was.
    """
    if started_at.utcoffset() is None or (upd is not None and upd.utcoffset() is None):
        raise BrixxError("mark_success needs timezone-aware datetimes")
    _lock(session, state)
    _require_owner(state, run_id)
    if upd is not None:
        capped = min(upd, started_at)
        if state.last_success_upd is None or capped > state.last_success_upd:
            state.last_success_upd = capped
    state.last_page = 0
    state.last_error = None
    session.flush()


def _lock(session: Session, state: BrixxSyncTableState) -> None:
    """Re-read the state row under a row lock, so overlapping runs serialise on it."""
    session.refresh(state, with_for_update=True)


def _require_owner(state: BrixxSyncTableState, run_id: UUID) -> None:
    if state.last_run_id != run_id:
        raise StaleRunError(f"BRIXX table {state.table_name!r} is owned by another run")


def mark_error(session: Session, state: BrixxSyncTableState, error: str) -> None:
    """Record a failure. The watermark and `last_page` are untouched, so the next attempt resumes."""
    state.last_error = error
    session.flush()


def describe_error(exc: BaseException, table: str, page: int) -> str:
    """The only error text we persist: class name, table and page (never the message)."""
    return f"{type(exc).__name__} table={table} page={page}"
