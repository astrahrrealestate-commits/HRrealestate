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
from sqlalchemy.orm import Session

from app.channels.brixx.models import BrixxTable
from app.channels.brixx.ports import BrixxApi
from app.channels.brixx.query import build_filter
from app.core.errors import BrixxError
from app.directory.brixx.schema import INCREMENTAL_COLUMN, has_incremental_column
from app.directory.brixx.state import describe_error, get_or_create_table_state, mark_error, record_page
from app.directory.brixx.upsert import upsert_page

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
    """A BRIXX timestamp as aware UTC. Naive values are Europe/Amsterdam local time; unparseable ones are None."""
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, date):
        parsed = datetime.combine(value, time.min, tzinfo=BRIXX_TZ)
    elif isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.strip())
        except ValueError:
            return None
    else:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=BRIXX_TZ)
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
    page: int,
    since: datetime | None,
    now: datetime,
) -> PageResult:
    """Fetch and store one page, then commit it together with `last_page` (one page, one transaction)."""
    try:
        fetched = api.fetch_page(info.name, page=page, filters=incremental_filter(info, since))
        upserted = upsert_page(session, table, info, company_id, fetched.rows, now)
        state = get_or_create_table_state(session, company_id, info.name)
        record_page(session, state, page, upserted.written)
        if detect_drift(info, table) or upserted.extra_columns:
            state.drifted = True
        session.commit()
    except BrixxError as exc:
        session.rollback()
        _record_failure(session, company_id, info.name, page, exc)
        raise
    except Exception:
        session.rollback()
        raise
    log.info("brixx.sync_page", table=info.name, page=page, written=upserted.written, has_next=fetched.has_next)
    return PageResult(fetched.has_next, upserted.written, _page_max_upd(fetched.rows), upserted.extra_columns)


def _record_failure(session: Session, company_id: UUID, table_name: str, page: int, exc: BrixxError) -> None:
    mark_error(
        session, get_or_create_table_state(session, company_id, table_name), describe_error(exc, table_name, page)
    )
    session.commit()
    log.warning("brixx.sync_page_failed", table=table_name, page=page, error=type(exc).__name__)
