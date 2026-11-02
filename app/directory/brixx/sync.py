"""Sync one page of one BRIXX table into the mirror, and detect schema drift.

`sync_table_page` is the unit DBOS retries: fetch (no DB held), then upsert plus `record_page` in ONE transaction that
it commits itself. A failure rolls the page back, records the error class on the table state and re-raises:
`BrixxAuthError` is not retryable (the token must be replaced), other `BrixxError`s are retried by the caller.
The watermark (`last_success_upd`) is advanced only by `state.mark_success`, after the last page. Only table names,
page numbers, counts and error class names are logged.
"""

from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from uuid import UUID
from zoneinfo import ZoneInfo

import sqlalchemy as sa
import structlog
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from app.channels.brixx.models import BrixxTable
from app.channels.brixx.ports import BrixxApi
from app.channels.brixx.query import build_filter
from app.core.errors import BrixxError, BrixxStoreError, StaleRunError
from app.directory.brixx.schema import INCREMENTAL_COLUMN, has_incremental_column
from app.directory.brixx.state import describe_error, get_or_create_table_state, mark_error, record_page
from app.directory.brixx.upsert import UpsertResult, upsert_page

log = structlog.get_logger()

OVERLAP = timedelta(minutes=5)
_SLACK = timedelta(days=1)
BRIXX_TZ = ZoneInfo("Europe/Amsterdam")


@dataclass(frozen=True)
class PageResult:
    has_next: bool
    written: int
    max_upd: datetime | None
    extra_columns: frozenset[str]


def incremental_filter(info: BrixxTable, since: datetime | None) -> str | None:
    """The BRIXX filter for rows changed since `since`, or None when the whole table must be fetched.

    None for a first run (`since` is None) and for tables without `UPDDATETIME`. Only `>=` on a date is used
    (BRIXX filters take `yyyy-MM-dd`). `since` is converted to Europe/Amsterdam (BRIXX timestamps are naive local
    time), backed off by OVERLAP (5 minutes) AND one extra full day before taking the date, so a timezone mismatch
    between BRIXX and UTC can never skip rows. Re-fetching overlapping rows is normal: upserts are idempotent.
    """
    if since is None or not has_incremental_column(info):
        return None
    if since.utcoffset() is None:
        raise BrixxError("incremental watermark must be timezone-aware")
    start = since.astimezone(BRIXX_TZ) - OVERLAP - _SLACK
    return build_filter((INCREMENTAL_COLUMN, ">=", start.date()))


def detect_drift(info: BrixxTable, table: sa.Table) -> bool:
    """True when BRIXX reports fields that the mirror table has no column for."""
    mirrored = {c.name for c in table.c}
    return any(f.name.lower() not in mirrored for f in info.fields)


def parse_upddatetime(value: object) -> datetime | None:
    """A BRIXX timestamp as aware UTC. Naive values are Europe/Amsterdam local time; unparseable ones are None.

    Around DST the earlier instant wins, so a watermark is never later than the true time: an ambiguous autumn time
    (02:30 on the switch-back day) is read as the first occurrence, and a nonexistent spring-forward time maps to the
    earlier of its two readings.
    """
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, date):
        parsed = datetime.combine(value, time.min)
    elif isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.strip())
        except ValueError:
            return None
    else:
        return None
    if parsed.tzinfo is None:
        return min(parsed.replace(tzinfo=BRIXX_TZ, fold=fold).astimezone(UTC) for fold in (0, 1))
    return parsed.astimezone(UTC)


def latest(first: datetime | None, second: datetime | None) -> datetime | None:
    """The later of two optional timestamps: how a caller folds per-page `max_upd` into the run's value."""
    if first is None or second is None:
        return first or second
    return max(first, second)


def _page_max_upd(rows: list[dict[str, object]]) -> datetime | None:
    found: datetime | None = None
    for row in rows:
        for key, value in row.items():
            if key.lower() == INCREMENTAL_COLUMN:
                found = latest(found, parse_upddatetime(value))
    return found


def sync_table_page(
    session: Session,
    api: BrixxApi,
    company_id: UUID,
    info: BrixxTable,
    table: sa.Table,
    *,
    run_id: UUID,
    page: int,
    since: datetime | None,
    now: datetime,
) -> PageResult:
    """Fetch and store one page of `run_id`, then commit it together with `last_page` (one page, one transaction).

    Fetches are ordered by the immutable primary key (lower-case), so an update mid-run cannot shift page-number
    pages. Failures roll the page back. `StaleRunError` (another run owns the table) leaves the state untouched; any
    other BrixxError or database error is recorded as class name, table and page, and re-raised (database errors as
    `BrixxStoreError`, with no SQL or row values in the message).
    """
    try:
        filters = incremental_filter(info, since)
        fetched = api.fetch_page(info.name, page=page, filters=filters, order_by=info.primary_key.lower())
        upserted = _store_page(session, company_id, info, table, run_id, page, fetched.rows, now)
    except StaleRunError:
        session.rollback()
        raise
    except (BrixxError, DBAPIError) as exc:
        session.rollback()
        _record_failure(session, company_id, info.name, page, run_id, exc)
        if isinstance(exc, DBAPIError):
            raise BrixxStoreError(describe_error(exc, info.name, page)) from None
        raise
    except Exception:
        session.rollback()
        raise
    log.info("brixx.sync_page", table=info.name, page=page, written=upserted.written, has_next=fetched.has_next)
    return PageResult(fetched.has_next, upserted.written, _page_max_upd(fetched.rows), upserted.extra_columns)


def _store_page(
    session: Session,
    company_id: UUID,
    info: BrixxTable,
    table: sa.Table,
    run_id: UUID,
    page: int,
    rows: list[dict[str, object]],
    now: datetime,
) -> UpsertResult:
    """Upsert the rows, advance the resume point, flag drift and commit, all in one transaction."""
    upserted = upsert_page(session, table, info, company_id, rows, now)
    state = get_or_create_table_state(session, company_id, info.name)
    record_page(session, state, page, upserted.written, run_id)
    if detect_drift(info, table) or upserted.extra_columns:
        state.drifted = True
    session.commit()
    return upserted


def _record_failure(
    session: Session, company_id: UUID, table_name: str, page: int, run_id: UUID, exc: Exception
) -> None:
    """Persist the failure on the state row if `run_id` still owns it. Never raises: the caller re-raises `exc`."""
    try:
        state = get_or_create_table_state(session, company_id, table_name)
        if state.last_run_id == run_id:
            mark_error(session, state, describe_error(exc, table_name, page))
            session.commit()
    except Exception as failure:
        session.rollback()
        log.warning("brixx.record_failure_failed", table=table_name, page=page, error=type(failure).__name__)
        return
    log.warning("brixx.sync_page_failed", table=table_name, page=page, error=type(exc).__name__)
