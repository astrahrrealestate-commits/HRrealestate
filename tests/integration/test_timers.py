"""Due-work timers: schedule once per dedupe key, claim with SKIP LOCKED + lease, fire each due timer once."""

import time
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

import pytest
from dbos import DBOS
from sqlalchemy import Engine
from sqlalchemy.orm import Session

from app.core.settings import Settings
from app.db.enums import TimerStatus
from app.db.models import Company, Timer
from app.pipeline import timers
from app.workflows import timer_dispatch
from app.workflows.deps import set_engine
from app.workflows.runtime import launch

pytestmark = pytest.mark.integration
NOW = datetime(2026, 10, 7, 9, 0, tzinfo=UTC)


def _schedule(engine: Engine, company_id: UUID, key: str, due: datetime, kind: str = "test.kind") -> UUID:
    with Session(engine) as s:
        timer_id = timers.schedule(s, company_id, kind, due, {"n": 1}, dedupe_key=key)
        s.commit()
    return timer_id


def _status(engine: Engine, timer_id: UUID) -> TimerStatus:
    with Session(engine) as s:
        row = s.get(Timer, timer_id)
        assert row is not None
        return row.status


def test_schedule_is_idempotent_per_dedupe_key(migrated_engine: Engine, committed_company: Company) -> None:
    first = _schedule(migrated_engine, committed_company.id, "k1", NOW)
    assert _schedule(migrated_engine, committed_company.id, "k1", NOW + timedelta(hours=1)) == first


def test_claim_takes_due_rows_once_until_lease_expires(migrated_engine: Engine, committed_company: Company) -> None:
    due = _schedule(migrated_engine, committed_company.id, "due", NOW - timedelta(minutes=1))
    _schedule(migrated_engine, committed_company.id, "later", NOW + timedelta(hours=1))
    claimed = timers.claim_due(migrated_engine, NOW)
    assert [c.id for c in claimed] == [due]
    assert claimed[0].attempts == 1
    assert timers.claim_due(migrated_engine, NOW) == []  # running, lease not expired
    reclaimed = timers.claim_due(migrated_engine, NOW + timers.LEASE + timedelta(seconds=1))
    assert [(c.id, c.attempts) for c in reclaimed] == [(due, 2)]


def test_claim_gives_up_after_max_attempts(migrated_engine: Engine, committed_company: Company) -> None:
    tid = _schedule(migrated_engine, committed_company.id, "flaky", NOW)
    at = NOW
    for _ in range(timers.MAX_ATTEMPTS):
        assert timers.claim_due(migrated_engine, at)
        at += timers.LEASE + timedelta(seconds=1)
    assert timers.claim_due(migrated_engine, at) == []
    assert _status(migrated_engine, tid) is TimerStatus.failed


def test_cancel_by_dedupe_key(migrated_engine: Engine, committed_company: Company) -> None:
    tid = _schedule(migrated_engine, committed_company.id, "c1", NOW)
    with Session(migrated_engine) as s:
        assert timers.cancel(s, committed_company.id, "c1") is True
        s.commit()
    assert _status(migrated_engine, tid) is TimerStatus.cancelled
    assert timers.claim_due(migrated_engine, NOW) == []


@pytest.fixture
def executor(test_settings: Settings, migrated_engine: Engine) -> Iterator[list[dict[str, Any]]]:
    calls: list[dict[str, Any]] = []
    DBOS.destroy()
    launch(test_settings, reset_for_tests=True, schedules=False)
    set_engine(migrated_engine)
    timer_dispatch.register("test.kind", lambda claimed: calls.append(dict(claimed.payload)))
    yield calls
    timer_dispatch.unregister("test.kind")
    set_engine(None)
    DBOS.destroy()


def _wait_status(engine: Engine, timer_id: UUID, want: TimerStatus) -> None:
    deadline = time.monotonic() + 20
    while _status(engine, timer_id) is not want:
        assert time.monotonic() < deadline, f"timer never reached {want}"
        time.sleep(0.1)


def test_sweep_fires_handler_once_and_marks_done(
    executor: list[dict[str, Any]], migrated_engine: Engine, committed_company: Company
) -> None:
    tid = _schedule(migrated_engine, committed_company.id, "fire", NOW)
    DBOS.start_workflow(timer_dispatch.sweep_due, NOW).get_result()
    DBOS.start_workflow(timer_dispatch.sweep_due, NOW).get_result()  # second sweep: nothing left to claim
    _wait_status(migrated_engine, tid, TimerStatus.done)
    assert executor == [{"n": 1}]


def test_unknown_kind_marks_timer_failed(
    executor: list[dict[str, Any]], migrated_engine: Engine, committed_company: Company
) -> None:
    tid = _schedule(migrated_engine, committed_company.id, "unknown", NOW, kind="nobody.handles")
    DBOS.start_workflow(timer_dispatch.sweep_due, NOW).get_result()
    _wait_status(migrated_engine, tid, TimerStatus.failed)
