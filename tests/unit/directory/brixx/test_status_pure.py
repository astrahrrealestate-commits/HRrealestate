"""BRIXX sync status read model, pure parts: the staleness window, per-table last success and lag."""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.contracts.brixx import BrixxRun, BrixxRunKind, BrixxRunStatus, BrixxStatus, BrixxTableStatus
from app.directory.brixx.status import STALE_AFTER_INTERVALS, is_stale, lag_seconds, table_last_success

NOW = datetime(2026, 11, 3, 12, 0, tzinfo=UTC)
WATERMARK = NOW - timedelta(hours=5)
RUN_START = NOW - timedelta(minutes=10)


def test_window_is_three_intervals() -> None:
    assert STALE_AFTER_INTERVALS == 3


@pytest.mark.parametrize(
    ("age", "interval", "stale"),
    [
        (timedelta(minutes=10), 15, False),
        (timedelta(minutes=45), 15, False),  # exactly at the window: still fresh
        (timedelta(minutes=45, seconds=1), 15, True),
        (timedelta(minutes=50), 20, False),  # the window scales with the interval
        (timedelta(minutes=61), 20, True),
    ],
)
def test_is_stale_uses_three_times_the_interval(age: timedelta, interval: int, stale: bool) -> None:
    assert is_stale(NOW - age, NOW, interval) is stale


def test_never_succeeded_is_stale() -> None:
    assert is_stale(None, NOW, 15) is True


def test_table_finished_clean_in_its_last_run_reports_that_runs_start() -> None:
    assert table_last_success(last_page=0, last_error=None, run_started_at=RUN_START, watermark=WATERMARK) == RUN_START


@pytest.mark.parametrize(
    ("last_page", "last_error"),
    [(3, None), (0, "BrixxAuthError table=PRG_RELATIE page=1"), (2, "BrixxError table=PRG_RELATIE page=3")],
)
def test_table_mid_run_or_failed_falls_back_to_the_watermark(last_page: int, last_error: str | None) -> None:
    got = table_last_success(last_page=last_page, last_error=last_error, run_started_at=RUN_START, watermark=WATERMARK)
    assert got == WATERMARK


def test_table_without_run_or_watermark_has_no_success() -> None:
    assert table_last_success(last_page=0, last_error=None, run_started_at=None, watermark=None) is None
    assert table_last_success(last_page=2, last_error=None, run_started_at=RUN_START, watermark=None) is None


def test_lag_is_whole_seconds_since_success_and_never_negative() -> None:
    assert lag_seconds(None, NOW) is None
    assert lag_seconds(NOW - timedelta(minutes=2, milliseconds=900), NOW) == 120
    assert lag_seconds(NOW + timedelta(seconds=5), NOW) == 0  # clock skew between worker and api


def test_status_contract_is_strict() -> None:
    table = BrixxTableStatus(
        name="PRG_RELATIE", row_count=3, last_success_at=RUN_START, lag_seconds=600, drifted=False, last_error=None
    )
    run = BrixxRun(
        id=uuid4(),
        kind=BrixxRunKind.incremental,
        status=BrixxRunStatus.succeeded,
        started_at=RUN_START,
        finished_at=NOW,
        error=None,
    )
    status = BrixxStatus(last_run=run, tables=[table], total_rows=3, stale=False)
    assert status.model_dump(mode="json")["tables"][0]["name"] == "PRG_RELATIE"
    naive = NOW.replace(tzinfo=None)
    with pytest.raises(ValidationError):
        BrixxTableStatus(name="X", row_count=0, last_success_at=naive, lag_seconds=0, drifted=False, last_error=None)
    with pytest.raises(ValidationError):
        BrixxStatus(last_run=None, tables=[], total_rows=0, stale=True, token="x")  # type: ignore[call-arg]
