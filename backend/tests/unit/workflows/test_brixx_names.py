"""BRIXX workflow names, deterministic ids and the schedule entry (no database, no executor)."""

from datetime import UTC, datetime, timedelta, timezone
from uuid import UUID

from app.core.workflow_names import BRIXX_QUEUE, BRIXX_SYNC_ALL, BRIXX_SYNC_TABLE, brixx_run_workflow_id
from app.workflows.brixx_sync import brixx_run_id
from app.workflows.runtime import SCHEDULES

COMPANY = UUID("018f0000-0000-7000-8000-000000000001")
WHEN = datetime(2026, 11, 1, 8, 15, 3, tzinfo=UTC)


def test_names_and_workflow_id_are_fixed() -> None:
    assert (BRIXX_QUEUE, BRIXX_SYNC_ALL, BRIXX_SYNC_TABLE) == ("brixx", "brixx.sync_all", "brixx.sync_table")
    assert brixx_run_workflow_id("run-1", "PRG_DEMO") == "brixx:run-1:PRG_DEMO"


def test_run_id_is_deterministic_per_minute_and_company() -> None:
    assert brixx_run_id(COMPANY, WHEN) == brixx_run_id(COMPANY, WHEN.replace(second=59))
    assert brixx_run_id(COMPANY, WHEN) != brixx_run_id(COMPANY, WHEN + timedelta(minutes=15))
    assert brixx_run_id(COMPANY, WHEN) != brixx_run_id(UUID(int=COMPANY.int + 1), WHEN)


def test_run_id_reads_the_instant_in_utc() -> None:
    amsterdam = timezone(timedelta(hours=1))
    assert brixx_run_id(COMPANY, WHEN) == brixx_run_id(COMPANY, WHEN.astimezone(amsterdam))


def test_schedule_runs_every_fifteen_minutes() -> None:
    [entry] = [s for s in SCHEDULES if s["schedule_name"] == BRIXX_SYNC_ALL]
    assert entry["schedule"] == "*/15 * * * *"
