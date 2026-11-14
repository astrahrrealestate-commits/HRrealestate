"""Worker process: runs DBOS workflows, queues and schedules.

    python -m app.worker              # run until SIGTERM/SIGINT (a second signal forces exit)
    python -m app.worker --selfcheck  # enqueue a probe on the running worker(s); exit 0 iff it completes in time

Phase 1 runs exactly one worker. DBOS recovers PENDING workflows by executor id (`DBOS__VMID`, default "local"), so
scaling out needs a stable, unique `DBOS__VMID` per replica (see docs/adr/0001).
"""

import argparse
import signal
import threading
import time
from types import FrameType

from dbos import DBOS, DBOSClient

from app.channels.registry import assert_channels_ready
from app.core.ids import new_id
from app.core.logging import configure_logging, get_logger
from app.core.settings import Settings, get_settings
from app.core.startup import assert_production_safe
from app.core.telemetry import init_telemetry
from app.llm.runtime import instrument_agents
from app.workflows.deps import get_deps
from app.workflows.queues import PIPELINE_QUEUE
from app.workflows.runtime import launch

SELFCHECK_TIMEOUT_SEC = 30.0
_IN_FLIGHT = {"ENQUEUED", "PENDING"}

log = get_logger(__name__)


def selfcheck(settings: Settings, timeout_sec: float = SELFCHECK_TIMEOUT_SEC, poll_sec: float = 0.2) -> bool:
    """True iff some running executor dequeues and completes a probe workflow before the deadline.

    Never blocks past the deadline (DBOS `get_result` has no timeout); a probe that timed out is cancelled so it
    cannot run later.
    """
    client = DBOSClient(system_database_url=settings.dbos_database_url)
    workflow_id = f"selfcheck:{new_id()}"
    try:
        client.enqueue({"queue_name": PIPELINE_QUEUE, "workflow_name": "system.selfcheck", "workflow_id": workflow_id})
        deadline = time.monotonic() + timeout_sec
        while time.monotonic() < deadline:
            status = client.retrieve_workflow(workflow_id).get_status()
            if status.status not in _IN_FLIGHT:
                return status.status == "SUCCESS" and status.output == "ok"
            time.sleep(poll_sec)
        client.cancel_workflow(workflow_id)
        log.error("worker.selfcheck.timeout", timeout_sec=timeout_sec, workflow_id=workflow_id)
        return False
    finally:
        client.destroy()


def run_forever(settings: Settings) -> None:
    stop = threading.Event()

    def _shutdown(signum: int, _frame: FrameType | None) -> None:
        log.info("worker.shutdown", signal=signum)
        signal.signal(signal.SIGTERM, signal.SIG_DFL)  # a second signal kills immediately
        signal.signal(signal.SIGINT, signal.SIG_DFL)
        stop.set()

    signal.signal(signal.SIGTERM, _shutdown)
    signal.signal(signal.SIGINT, _shutdown)
    launch(settings)
    log.info("worker.started", version=settings.app_version)
    stop.wait()
    DBOS.destroy(workflow_completion_timeout_sec=20)  # compose stop_grace_period must exceed this (40s)
    log.info("worker.stopped")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="app.worker")
    parser.add_argument("--selfcheck", action="store_true", help="verify a running worker executes queued work")
    args = parser.parse_args(argv)

    settings = get_settings()
    assert_production_safe(settings)
    assert_channels_ready(settings)
    configure_logging(settings.env)
    init_telemetry(settings)
    instrument_agents(settings)  # LLM spans → Langfuse (agents run only in the worker)
    if args.selfcheck:
        ok = selfcheck(settings, timeout_sec=SELFCHECK_TIMEOUT_SEC)
        log.info("worker.selfcheck", ok=ok)
        return 0 if ok else 1
    get_deps()  # build storage, engine and adapters now: bad config fails at boot, not in the first step
    run_forever(settings)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
