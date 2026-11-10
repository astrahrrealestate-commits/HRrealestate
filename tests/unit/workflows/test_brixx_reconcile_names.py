"""BRIXX reconcile and mapper workflow names, deterministic ids and the daily schedule (no database, no executor)."""

from datetime import UTC, datetime, timedelta
from uuid import UUID

from app.core.workflow_names import (
    BRIXX_MAP_DIRECTORY,
    BRIXX_RECONCILE_ALL,
    BRIXX_RECONCILE_TABLE,
    brixx_map_workflow_id,
    brixx_reconcile_workflow_id,
)
from app.directory.brixx.reconcile import keyset_filter
from app.workflows.brixx_reconcile import reconcile_all, reconcile_run_id
from app.workflows.runtime import SCHEDULES

COMPANY = UUID("018f0000-0000-7000-8000-000000000001")
TICK = datetime(2026, 11, 3, 2, 0, tzinfo=UTC)


def test_names_and_ids_are_fixed() -> None:
    assert (BRIXX_RECONCILE_ALL, BRIXX_RECONCILE_TABLE, BRIXX_MAP_DIRECTORY) == (
        "brixx.reconcile_all",
        "brixx.reconcile_table",
        "brixx.map_directory",
    )
    assert brixx_reconcile_workflow_id("run-1", "PRG_VHE") == "brixxrec:run-1:PRG_VHE"
    assert brixx_map_workflow_id("run-1") == "brixxmap:run-1"


def test_reconcile_run_id_is_one_per_company_and_day() -> None:
    assert reconcile_run_id(COMPANY, TICK) == reconcile_run_id(COMPANY, TICK + timedelta(hours=3))
    assert reconcile_run_id(COMPANY, TICK) != reconcile_run_id(COMPANY, TICK + timedelta(days=1))
    assert reconcile_run_id(COMPANY, TICK) != reconcile_run_id(UUID(int=COMPANY.int + 1), TICK)


def test_reconcile_is_scheduled_daily_at_three_amsterdam_time() -> None:
    [entry] = [s for s in SCHEDULES if s["schedule_name"] == "brixx.reconcile_all"]
    assert entry["workflow_fn"] is reconcile_all
    assert (entry["schedule"], entry.get("cron_timezone")) == ("0 3 * * *", "Europe/Amsterdam")


def test_keyset_filter_starts_unfiltered_then_pages_after_the_cursor() -> None:
    assert keyset_filter("prg_vheid", None) is None
    assert keyset_filter("prg_vheid", 41) == "[prg_vheid > 41]"
