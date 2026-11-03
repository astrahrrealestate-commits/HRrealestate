"""Daily BRIXX reconcile: cron parent `brixx.reconcile_all` and one queued child per table, `brixx.reconcile_table`.

The parent mirrors `brixx.sync_all`: first company, list tables, insert and commit a `reconcile` run, enqueue one
child per table on the `brixx` queue, then record the run's final status and map the directory. Ids are deterministic:
the run id is a uuid5 of company + cron day (UTC date of the tick), the child id is `brixxrec:<run_id>:<table>`. A child
scans keyset pages of primary keys (one step each, staged in Postgres) and applies the result in one step; it never
raises for a failed table, it returns `failed:<ErrorClass>`. Workflow bodies only sequence steps (no I/O, no clock).
"""

from datetime import UTC, datetime
from typing import Any
from uuid import NAMESPACE_URL, UUID, uuid5

import sqlalchemy as sa
from dbos import DBOS, SetWorkflowID
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import Session

from app.core.logging import get_logger
from app.core.workflow_names import BRIXX_RECONCILE_ALL, BRIXX_RECONCILE_TABLE, brixx_reconcile_workflow_id
from app.db.enums import BrixxRunKind
from app.db.models.brixx import BrixxSyncRun
from app.directory.brixx.reconcile import apply_reconcile, scan_page
from app.directory.brixx.schema import build_table
from app.workflows import queues
from app.workflows.brixx_map import map_after_run
from app.workflows.brixx_sync import (
    FAILED,
    OK,
    RETRY,
    collect,
    company_step,
    describe_step,
    error_name,
    finish_run_step,
    info_from_json,
    list_tables_step,
)
from app.workflows.deps import brixx_api, get_engine

log = get_logger(__name__)

_RUN_NAMESPACE = uuid5(NAMESPACE_URL, "https://estateos.invalid/brixx/reconcile-run")


def reconcile_run_id(company_id: UUID, scheduled_time: datetime) -> UUID:
    """The reconcile run of one day: the same company and UTC date always give the same id."""
    return uuid5(_RUN_NAMESPACE, f"brixx:{company_id}:reconcile:{scheduled_time.astimezone(UTC):%Y%m%d}")


@DBOS.step(name="brixx.create_reconcile_run", **RETRY)
def create_reconcile_run_step(company_id: str, scheduled_iso: str) -> str:
    """Insert and commit the run before any child is enqueued. A replayed tick keeps the original row."""
    cid = UUID(company_id)
    run_id = reconcile_run_id(cid, datetime.fromisoformat(scheduled_iso))
    with Session(get_engine()) as session:
        session.execute(
            postgresql.insert(BrixxSyncRun)
            .values(id=run_id, company_id=cid, kind=BrixxRunKind.reconcile, started_at=datetime.now(UTC))
            .on_conflict_do_nothing(index_elements=["id"])
        )
        session.commit()
    return str(run_id)


@DBOS.workflow(name=BRIXX_RECONCILE_ALL)
def reconcile_all(scheduled_time: datetime, context: Any) -> None:
    """Daily: one reconcile run, a `brixx.reconcile_table` child per BRIXX table, the final status, then the mapper."""
    company_id = company_step()
    if company_id is None:
        log.info("brixx.reconcile_skipped", reason="no_company")
        return
    try:
        tables, listing_error = list_tables_step(), None
    except Exception as exc:  # BrixxAuthError is not retried; anything else outlived its retries
        tables, listing_error = [], error_name(exc)
    if not tables and listing_error is None:
        log.info("brixx.reconcile_skipped", reason="no_tables")
        return
    run_id = create_reconcile_run_step(company_id, scheduled_time.astimezone(UTC).isoformat())
    if listing_error is not None:
        finish_run_step(company_id, run_id, f"list_tables failed: {listing_error}")
        return
    handles = []
    for table in tables:
        with SetWorkflowID(brixx_reconcile_workflow_id(run_id, table)):
            handles.append((table, queues.brixx_queue().enqueue(reconcile_table, run_id, table)))
    failures = [f"{table} ({outcome})" for table, outcome in ((t, collect(h)) for t, h in handles) if outcome != OK]
    finish_run_step(company_id, run_id, "tables failed: " + ", ".join(failures) if failures else None)
    map_after_run(run_id)  # soft-deleted rows end their people/units/leases


@DBOS.step(name="brixx.reconcile_begin", **RETRY)
def reconcile_begin_step(run_id: str) -> dict[str, str]:
    with Session(get_engine()) as session:
        run = session.scalars(sa.select(BrixxSyncRun).where(BrixxSyncRun.id == UUID(run_id))).one()
        return {"company_id": str(run.company_id), "started_at": run.started_at.astimezone(UTC).isoformat()}


@DBOS.step(name="brixx.reconcile_scan", **RETRY)
def scan_step(company_id: str, run_id: str, info: dict[str, Any], cursor: int | None) -> dict[str, Any]:
    with Session(get_engine()) as session:
        result = scan_page(session, brixx_api(), UUID(company_id), info_from_json(info), UUID(run_id), cursor)
    return {"cursor": result.cursor, "has_next": result.has_next}


@DBOS.step(name="brixx.reconcile_apply", **RETRY)
def apply_step(company_id: str, run_id: str, info: dict[str, Any], started_at: str) -> dict[str, int]:
    table_info = info_from_json(info)
    with Session(get_engine()) as session:
        result = apply_reconcile(
            session,
            UUID(company_id),
            table_info,
            build_table(table_info, sa.MetaData()),
            run_id=UUID(run_id),
            run_started_at=datetime.fromisoformat(started_at),
            now=datetime.now(UTC),
        )
    return {"soft_deleted": result.soft_deleted, "restored": result.restored, "missing": result.missing}


def _reconcile(run_id: str, table: str) -> None:
    info = describe_step(table)
    begun = reconcile_begin_step(run_id)
    cursor: int | None = None
    while True:
        page = scan_step(begun["company_id"], run_id, info, cursor)
        cursor = page["cursor"]
        if not page["has_next"]:
            break
    apply_step(begun["company_id"], run_id, info, begun["started_at"])


@DBOS.workflow(name=BRIXX_RECONCILE_TABLE)
def reconcile_table(run_id: str, table: str) -> str:
    """Reconcile one table for `run_id`. Returns `ok` or `failed:<ErrorClass>`; a failed table never raises."""
    try:
        _reconcile(run_id, table)
    except Exception as exc:
        name = error_name(exc)
        log.warning("brixx.reconcile_table_failed", table=table, error=name)
        return FAILED + name
    return OK
