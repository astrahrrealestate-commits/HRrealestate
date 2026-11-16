"""BRIXX directory mapping workflow (`brixx.map_directory`, id `brixxmap:<run_id>`): mirror -> people/units/leases/rent.

Started by `brixx.sync_all` and `brixx.reconcile_all` as a child once their tables have finished (see
`map_after_run`). Four steps (people, units, leases, rent ledger), each one short transaction committed by the step; the
company comes from the run row. The workflow never raises: it returns `ok` or `failed:<ErrorClass>`, so a mapping
problem never fails the sync run (the mirror is already stored). Database errors are retried by the steps.
"""

from datetime import UTC, date, datetime
from typing import Any
from uuid import UUID

import sqlalchemy as sa
from dbos import DBOS, SetWorkflowID
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from app.core.logging import get_logger
from app.core.workflow_names import BRIXX_MAP_DIRECTORY, brixx_map_workflow_id
from app.db.models.brixx import BrixxSyncRun
from app.directory.brixx.mapper import MapCounts, map_leases, map_people, map_rent, map_units
from app.directory.brixx.name_check import name_gaps
from app.directory.brixx.sync import BRIXX_TZ
from app.workflows.deps import get_engine

log = get_logger(__name__)

OK = "ok"
FAILED = "failed:"
_RETRY: dict[str, Any] = {
    "retries_allowed": True,
    "max_attempts": 5,
    "interval_seconds": 2.0,
    "backoff_rate": 2.0,
    "should_retry": lambda exc: isinstance(exc, DBAPIError),
}


def _today() -> date:
    """BRIXX dates are Europe/Amsterdam calendar dates."""
    return datetime.now(UTC).astimezone(BRIXX_TZ).date()


def _run_part(part: str, company_id: str, mapper: Any) -> dict[str, int]:
    with Session(get_engine()) as session:
        counts: MapCounts = mapper(session, UUID(company_id), _today())
        session.commit()
    log.info("brixx.map_part", part=part, **counts.as_dict())
    return counts.as_dict()


@DBOS.step(name="brixx.map_company", **_RETRY)
def run_company_step(run_id: str) -> str | None:
    with Session(get_engine()) as session:
        found = session.scalar(sa.select(BrixxSyncRun.company_id).where(BrixxSyncRun.id == UUID(run_id)))
    return None if found is None else str(found)


@DBOS.step(name="brixx.map_people", **_RETRY)
def map_people_step(company_id: str) -> dict[str, int]:
    return _run_part("people", company_id, map_people)


@DBOS.step(name="brixx.map_units", **_RETRY)
def map_units_step(company_id: str) -> dict[str, int]:
    return _run_part("units", company_id, map_units)


@DBOS.step(name="brixx.map_leases", **_RETRY)
def map_leases_step(company_id: str) -> dict[str, int]:
    return _run_part("leases", company_id, map_leases)


@DBOS.step(name="brixx.map_rent", **_RETRY)
def map_rent_step(company_id: str) -> dict[str, int]:
    return _run_part("rent", company_id, map_rent)


@DBOS.step(name="brixx.check_names", **_RETRY)
def check_names_step() -> int:
    """Log every table or column group the code reads that the live mirror no longer has; returns how many."""
    with Session(get_engine()) as session:
        gaps = name_gaps(session)
    for gap in gaps:
        log.warning("brixx.name_gap", gap=gap)
    return len(gaps)


@DBOS.workflow(name=BRIXX_MAP_DIRECTORY)
def map_directory(run_id: str) -> str:
    """Map the mirror of the run's company into the directory. Returns `ok` or `failed:<ErrorClass>`."""
    try:
        company_id = run_company_step(run_id)
        if company_id is None:
            return FAILED + "UnknownRun"
        map_people_step(company_id)
        map_units_step(company_id)
        map_leases_step(company_id)
        map_rent_step(company_id)
        check_names_step()
    except Exception as exc:
        log.warning("brixx.map_failed", error=type(exc).__name__)
        return FAILED + type(exc).__name__
    return OK


def map_after_run(run_id: str) -> str:
    """Run the mapping of `run_id` as a child workflow (call from a workflow body; deterministic id)."""
    with SetWorkflowID(brixx_map_workflow_id(run_id)):
        return map_directory(run_id)
