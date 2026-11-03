"""BRIXX mirror sync workflows: a cron parent (`brixx.sync_all`) and one queued child per table (`brixx.sync_table`).

Phase 1 limit: there is exactly one company, so the parent syncs the first company by `created_at` (no companies: a
quiet no-op). Multi-company needs a per-company BRIXX token and schedule first.

Workflow bodies only sequence steps; every database, API and clock access is inside a `@DBOS.step`. Ids are
deterministic: the run id is a uuid5 of company + cron tick (minute), the child workflow id is
`brixx:<run_id>:<table>`, so a replayed cron tick or a repeated enqueue never duplicates a run, a child or a state row.

Failure policy: `BrixxAuthError` and `StaleRunError` are not retried (`should_retry` of the DBOS step; retrying cannot
help until the token is replaced or the rival run finishes). Other `BrixxError`/`BrixxStoreError`s and database errors
are retried with backoff. A child never raises for a failed table: it returns `failed:<ErrorClass>` so the parent can
mark the run `failed` (class and table names only) while the other tables finish. The fixed cron (`*/15`) does not
read `brixx_sync_interval_minutes`: that setting is not used for scheduling.
"""

from dataclasses import asdict
from datetime import UTC, datetime
from typing import Any
from uuid import NAMESPACE_URL, UUID, uuid5

import sqlalchemy as sa
from dbos import DBOS, SetWorkflowID
from sqlalchemy.dialects import postgresql
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from app.channels.brixx.models import BrixxField, BrixxTable
from app.core.errors import BrixxAuthError, BrixxError, StaleRunError
from app.core.logging import get_logger
from app.core.workflow_names import BRIXX_SYNC_ALL, BRIXX_SYNC_TABLE, brixx_run_workflow_id
from app.db.enums import BrixxRunKind, BrixxRunStatus
from app.db.models import Company
from app.db.models.brixx import BrixxSyncRun
from app.directory.brixx.schema import build_table
from app.directory.brixx.state import begin_table_run, get_or_create_table_state, mark_success
from app.directory.brixx.sync import latest, sync_table_page
from app.workflows import queues
from app.workflows.deps import brixx_api, get_engine

log = get_logger(__name__)

OK = "ok"
FAILED = "failed:"
_RUN_NAMESPACE = uuid5(NAMESPACE_URL, "https://estateos.invalid/brixx/sync-run")
_NOT_RETRIED = (BrixxAuthError, StaleRunError)
_MAX_ERROR = 1000


def _should_retry(exc: BaseException) -> bool:
    """Retry BRIXX and database errors, except those where another attempt cannot succeed."""
    return isinstance(exc, BrixxError | DBAPIError) and not isinstance(exc, _NOT_RETRIED)


RETRY: dict[str, Any] = {
    "retries_allowed": True,
    "max_attempts": 8,
    "interval_seconds": 5.0,
    "backoff_rate": 2.0,
    "should_retry": _should_retry,
}


def brixx_run_id(company_id: UUID, scheduled_time: datetime) -> UUID:
    """The run of one cron tick: the same company and minute (UTC) always give the same id."""
    tick = scheduled_time.astimezone(UTC)
    return uuid5(_RUN_NAMESPACE, f"brixx:{company_id}:incremental:{tick:%Y%m%dT%H%M}")


def error_name(exc: BaseException) -> str:
    """Class name of the error that mattered (the last attempt's, when DBOS gave up retrying)."""
    attempts = getattr(exc, "errors", None) if type(exc).__name__ == "DBOSMaxStepRetriesExceeded" else None
    return type(attempts[-1]).__name__ if attempts else type(exc).__name__


def info_from_json(data: dict[str, Any]) -> BrixxTable:
    return BrixxTable(data["name"], data["primary_key"], tuple(BrixxField(**f) for f in data["fields"]))


def _utc(value: datetime) -> str:
    return value.astimezone(UTC).isoformat()


@DBOS.step(name="brixx.first_company")
def company_step() -> str | None:
    with Session(get_engine()) as session:
        found = session.scalar(sa.select(Company.id).order_by(Company.created_at).limit(1))
    return None if found is None else str(found)


@DBOS.step(name="brixx.list_tables", **RETRY)
def list_tables_step() -> list[str]:
    return [name for name, _key in brixx_api().list_tables()]


@DBOS.step(name="brixx.create_run", **RETRY)
def create_run_step(company_id: str, scheduled_iso: str) -> str:
    """Insert and commit the run before any child is enqueued. A replayed tick keeps the original row."""
    cid = UUID(company_id)
    run_id = brixx_run_id(cid, datetime.fromisoformat(scheduled_iso))
    with Session(get_engine()) as session:
        session.execute(
            postgresql.insert(BrixxSyncRun)
            .values(id=run_id, company_id=cid, kind=BrixxRunKind.incremental, started_at=datetime.now(UTC))
            .on_conflict_do_nothing(index_elements=["id"])
        )
        session.commit()
    return str(run_id)


@DBOS.step(name="brixx.finish_run", **RETRY)
def finish_run_step(company_id: str, run_id: str, error: str | None) -> None:
    status = BrixxRunStatus.succeeded if error is None else BrixxRunStatus.failed
    with Session(get_engine()) as session:
        session.execute(
            sa.update(BrixxSyncRun)
            .where(BrixxSyncRun.id == UUID(run_id), BrixxSyncRun.company_id == UUID(company_id))
            .values(status=status, finished_at=datetime.now(UTC), error=error and error[:_MAX_ERROR])
        )
        session.commit()


@DBOS.workflow(name=BRIXX_SYNC_ALL)
def sync_all(scheduled_time: datetime, context: Any) -> None:
    """Every 15 minutes: one run, one `brixx.sync_table` child per BRIXX table, then the run's final status."""
    company_id = company_step()
    if company_id is None:
        log.info("brixx.sync_skipped", reason="no_company")
        return
    try:
        tables, listing_error = list_tables_step(), None
    except Exception as exc:  # BrixxAuthError is not retried; anything else outlived its retries
        tables, listing_error = [], error_name(exc)
    if not tables and listing_error is None:
        log.info("brixx.sync_skipped", reason="no_tables")  # e.g. the empty dev fake: no run rows, no noise
        return
    run_id = create_run_step(company_id, _utc(scheduled_time))
    if listing_error is not None:
        finish_run_step(company_id, run_id, f"list_tables failed: {listing_error}")
        return
    handles = []
    for table in tables:
        with SetWorkflowID(brixx_run_workflow_id(run_id, table)):
            handles.append((table, queues.brixx_queue().enqueue(sync_table, run_id, table)))
    failures = [f"{table} ({outcome})" for table, outcome in ((t, collect(h)) for t, h in handles) if outcome != OK]
    finish_run_step(company_id, run_id, "tables failed: " + ", ".join(failures) if failures else None)


def collect(handle: Any) -> str:
    try:
        result = str(handle.get_result())
    except Exception as exc:  # the child crashed instead of returning a failure marker
        return error_name(exc)
    return OK if result == OK else result.removeprefix(FAILED)


@DBOS.step(name="brixx.describe_table", **RETRY)
def describe_step(table: str) -> dict[str, Any]:
    info = brixx_api().describe_table(table)
    build_table(info, sa.MetaData())  # refuse unsafe names before anything is stored
    return asdict(info)


@DBOS.step(name="brixx.begin_table", **RETRY)
def begin_step(run_id: str, table: str) -> dict[str, Any]:
    """Commit the table's takeover by this run. Returns the first page, the incremental watermark and the run's
    ORIGINAL start (read from the run row, so a retried child never uses its own clock)."""
    with Session(get_engine()) as session:
        run = session.scalars(sa.select(BrixxSyncRun).where(BrixxSyncRun.id == UUID(run_id))).one_or_none()
        if run is None:
            raise BrixxError(f"unknown BRIXX sync run for table {table!r}")
        state = get_or_create_table_state(session, run.company_id, table)
        first_page = begin_table_run(session, state, run.id)
        since = state.last_success_upd
        out = {
            "company_id": str(run.company_id),
            "started_at": _utc(run.started_at),
            "page": first_page,
            "since": None if since is None else _utc(since),
        }
        session.commit()
    return out


@DBOS.step(name="brixx.sync_page", **RETRY)
def sync_page_step(company_id: str, run_id: str, info: dict[str, Any], page: int, since: str | None) -> dict[str, Any]:
    table_info = info_from_json(info)
    with Session(get_engine()) as session:
        result = sync_table_page(
            session,
            brixx_api(),
            UUID(company_id),
            table_info,
            build_table(table_info, sa.MetaData()),
            run_id=UUID(run_id),
            page=page,
            since=None if since is None else datetime.fromisoformat(since),
            now=datetime.now(UTC),
        )
    return {"has_next": result.has_next, "max_upd": None if result.max_upd is None else _utc(result.max_upd)}


@DBOS.step(name="brixx.mark_success", **RETRY)
def mark_success_step(company_id: str, run_id: str, table: str, upd: str | None, started_at: str) -> None:
    with Session(get_engine()) as session:
        state = get_or_create_table_state(session, UUID(company_id), table)
        newest = None if upd is None else datetime.fromisoformat(upd)
        mark_success(session, state, newest, datetime.fromisoformat(started_at), UUID(run_id))
        session.commit()


def _sync_pages(run_id: str, table: str) -> None:
    info = describe_step(table)
    begun = begin_step(run_id, table)
    page, upd = begun["page"], None
    while True:
        done = sync_page_step(begun["company_id"], run_id, info, page, begun["since"])
        newest = done["max_upd"]
        upd = latest(upd, None if newest is None else datetime.fromisoformat(newest))
        if not done["has_next"]:
            break
        page += 1
    mark_success_step(begun["company_id"], run_id, table, None if upd is None else _utc(upd), begun["started_at"])


@DBOS.workflow(name=BRIXX_SYNC_TABLE)
def sync_table(run_id: str, table: str) -> str:
    """Mirror one table for `run_id`. Returns `ok` or `failed:<ErrorClass>`; a failed table never raises, so the
    run's other tables are unaffected and DBOS does not retry the whole workflow."""
    try:
        _sync_pages(run_id, table)
    except Exception as exc:
        name = error_name(exc)
        log.warning("brixx.sync_table_failed", table=table, error=name)
        return FAILED + name
    return OK
