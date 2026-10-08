"""Timer dispatch: the minute sweep claims due timers and fires one `timer.fire` workflow per claim.

Handlers are registered per timer kind by the modules that own them (waits, tasks, briefings). A handler runs inside a
DBOS step, so it may do I/O; it must be idempotent (a lease-expired timer is fired again).
"""

from collections.abc import Callable
from dataclasses import asdict
from datetime import datetime
from typing import Any
from uuid import UUID

from dbos import DBOS, SetWorkflowID
from sqlalchemy import Engine

from app.core.logging import get_logger
from app.db.enums import TimerStatus
from app.pipeline import timers
from app.pipeline.timers import ClaimedTimer
from app.workflows import queues
from app.workflows.deps import get_engine

log = get_logger(__name__)
Handler = Callable[[ClaimedTimer], None]
_handlers: dict[str, Handler] = {}


def register(kind: str, handler: Handler) -> None:
    _handlers[kind] = handler


def unregister(kind: str) -> None:
    _handlers.pop(kind, None)


def _db() -> Engine:
    return get_engine()


@DBOS.step(name="timers.claim")
def claim_step(now_iso: str) -> list[dict[str, Any]]:
    claimed = timers.claim_due(_db(), datetime.fromisoformat(now_iso))
    return [{**asdict(c), "id": str(c.id), "company_id": str(c.company_id)} for c in claimed]


@DBOS.workflow(name="timers.sweep_due")
def sweep_due(now: datetime) -> int:
    claimed = claim_step(now.isoformat())
    for item in claimed:
        with SetWorkflowID(f"timer:{item['id']}:{item['attempts']}"):
            queues.timers_queue().enqueue(fire, item)
    return len(claimed)


@DBOS.step(name="timers.run_handler")
def run_handler_step(item: dict[str, Any]) -> str:
    claimed = ClaimedTimer(UUID(item["id"]), UUID(item["company_id"]), item["kind"], item["payload"], item["attempts"])
    handler = _handlers.get(claimed.kind)
    if handler is None:
        log.error("timer.unknown_kind", timer_id=item["id"], kind=claimed.kind)
        timers.finish(_db(), claimed.id, claimed.attempts, TimerStatus.failed)
        return "unknown"
    handler(claimed)
    timers.finish(_db(), claimed.id, claimed.attempts, TimerStatus.done)
    return "done"


@DBOS.workflow(name="timers.fire")
def fire(item: dict[str, Any]) -> str:
    """A handler error leaves the timer `running`; the lease expires and the next sweep retries (max attempts)."""
    return run_handler_step(item)
