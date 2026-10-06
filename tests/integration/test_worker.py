import os
import signal
import subprocess
import sys
import time
from pathlib import Path

import pytest
from dbos import DBOS, DBOSClient

from app.core.settings import Settings
from app.workflows.queues import PIPELINE_QUEUE
from app.workflows.runtime import launch
from app.workflows.system import selfcheck, timer_sweep

pytestmark = pytest.mark.integration
ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def no_worker(test_settings: Settings, migrated_engine: object) -> None:
    """DBOS system tables exist and are empty, but no executor runs in this process."""
    DBOS.destroy()
    launch(test_settings, reset_for_tests=True, schedules=False)
    DBOS.destroy()


def test_selfcheck_workflow_runs_directly(dbos_runtime: None) -> None:
    assert selfcheck() == "ok"


def test_same_workflow_id_runs_once(dbos_runtime: None, test_settings: Settings) -> None:
    client = DBOSClient(system_database_url=test_settings.dbos_database_url)
    try:
        opts = {"queue_name": PIPELINE_QUEUE, "workflow_name": "system.selfcheck", "workflow_id": "sc-dup-1"}
        first = client.enqueue(opts)  # type: ignore[arg-type]
        assert first.get_result(polling_interval_sec=0.1) == "ok"
        second = client.enqueue(opts)  # type: ignore[arg-type]
        assert second.get_result(polling_interval_sec=0.1) == "ok"
        assert second.get_status().created_at == first.get_status().created_at  # same run, not a re-execution
    finally:
        client.destroy()


def test_timer_sweep_scheduled_every_minute(dbos_runtime: None) -> None:
    schedules = {s["schedule_name"]: s for s in DBOS.list_schedules()}
    assert schedules["system.timer_sweep"]["schedule"] == "* * * * *"
    assert timer_sweep(scheduled_time=None, context=None) is None  # type: ignore[arg-type,func-returns-value]


def test_relaunch_is_idempotent_and_keeps_paused_schedule(dbos_runtime: None, test_settings: Settings) -> None:
    DBOS.pause_schedule("system.timer_sweep")
    DBOS.destroy()
    launch(test_settings)  # restart without reset, like a worker redeploy
    schedule = DBOS.get_schedule("system.timer_sweep")
    assert schedule is not None
    assert schedule["status"] == "PAUSED"


def test_cli_selfcheck_exits_1_without_worker(
    no_worker: None, test_settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    import app.worker

    monkeypatch.setattr(app.worker, "get_settings", lambda: test_settings)
    monkeypatch.setattr(app.worker, "SELFCHECK_TIMEOUT_SEC", 1.5)
    assert app.worker.main(["--selfcheck"]) == 1  # catches a future in-process launch() in the CLI path


def test_selfcheck_without_worker_fails_fast_and_cancels_probe(no_worker: None, test_settings: Settings) -> None:
    from app.worker import selfcheck as worker_selfcheck

    started = time.monotonic()
    assert worker_selfcheck(test_settings, timeout_sec=2, poll_sec=0.1) is False
    assert time.monotonic() - started < 6
    client = DBOSClient(system_database_url=test_settings.dbos_database_url)
    try:
        probes = [w for w in client.list_workflows() if w.workflow_id.startswith("selfcheck:")]
        assert [w.status for w in probes] == ["CANCELLED"]
    finally:
        client.destroy()


def test_separate_worker_process_passes_selfcheck_and_stops_on_sigterm(
    no_worker: None, test_settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    import app.worker

    env = {**os.environ, "DATABASE_URL": str(test_settings.database_url), "ENV": "test", "SENTRY_DSN": ""}
    proc = subprocess.Popen([sys.executable, "-m", "app.worker"], cwd=ROOT, env=env)
    try:
        monkeypatch.setattr(app.worker, "get_settings", lambda: test_settings)
        assert app.worker.main(["--selfcheck"]) == 0  # this process never launched DBOS
        proc.send_signal(signal.SIGTERM)
        assert proc.wait(timeout=40) == 0
    finally:
        if proc.poll() is None:
            proc.kill()
