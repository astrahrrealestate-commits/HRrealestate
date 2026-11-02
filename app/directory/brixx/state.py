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

from app.core.errors import BrixxError
from app.db.models.brixx import BrixxSyncTableState


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
    """First page to fetch for `run_id`: `last_page + 1` when this same run was interrupted, otherwise 1."""
    if state.last_run_id == run_id and state.last_page > 0:
        return state.last_page + 1
    state.last_run_id = run_id
    state.last_page = 0
    state.row_count = 0
    session.flush()
    return 1


def record_page(session: Session, state: BrixxSyncTableState, page: int, written: int) -> None:
    """Mark `page` fully committed. A replayed page (at or below `last_page`) is not counted twice."""
    if page > state.last_page:
        state.last_page = page
        state.row_count += written
    state.last_error = None
    session.flush()


def mark_success(session: Session, state: BrixxSyncTableState, upd: datetime | None, started_at: datetime) -> None:
    """Finish the table: advance the watermark and clear the resume point. Call only after the last page.

    The watermark never moves backwards and is capped at `started_at` so a future-dated row cannot skip later
    changes; `upd=None` (no timestamps seen) leaves it as it was.
    """
    if upd is not None:
        capped = min(upd, started_at)
        if state.last_success_upd is None or capped > state.last_success_upd:
            state.last_success_upd = capped
    state.last_page = 0
    state.last_error = None
    session.flush()


def mark_error(session: Session, state: BrixxSyncTableState, error: str) -> None:
    """Record a failure. The watermark and `last_page` are untouched, so the next attempt resumes."""
    state.last_error = error
    session.flush()


def describe_error(exc: BaseException, table: str, page: int) -> str:
    """The only error text we persist: class name, table and page (never the message)."""
    return f"{type(exc).__name__} table={table} page={page}"
