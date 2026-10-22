"""DBOS queues. Registered (persisted to the system DB) after launch; handles kept for workflow bodies.

Workflow bodies use these module-level handles instead of `DBOS.retrieve_queue`, so they do no system-DB reads.

The `concierge` queue (Super Agent turns, spec amendment 2026-10-22) keeps chat turns from waiting behind pipeline
work. Its worker polls every `CONCIERGE_POLL_SECONDS` instead of DBOS's default 1 s: each poll is one dequeue
transaction (plus a config reload) on the system database per worker, about 8 small queries/s per worker. DBOS accepts
any positive interval and backs off on its own under contention (doubling up to 120 s, then easing back), so 0.25 s
is the short end that stays cheap; a turn now waits at most about a quarter second to be picked up when a slot is free.
At most `Settings.concierge_worker_concurrency` turns run at once per worker (each is mostly a model call).
"""

from dbos import DBOS, Queue

from app.core.settings import Settings
from app.core.workflow_names import CONCIERGE_QUEUE, DOCUMENTS_QUEUE, GMAIL_SYNC_QUEUE, PIPELINE_QUEUE, TIMERS_QUEUE

__all__ = [
    "CONCIERGE_POLL_SECONDS",
    "CONCIERGE_QUEUE",
    "DOCUMENTS_QUEUE",
    "GMAIL_SYNC_QUEUE",
    "PIPELINE_QUEUE",
    "PIPELINE_WORKER_CONCURRENCY",
    "concierge_queue",
    "documents_queue",
    "gmail_sync_queue",
    "pipeline_queue",
]

PIPELINE_WORKER_CONCURRENCY = 4  # per executor; keeps one VM from overrunning LLM rate limits
CONCIERGE_POLL_SECONDS = 0.25  # chat queue poll interval (DBOS default: 1.0)
_handles: dict[str, Queue] = {}


def register_queues(settings: Settings) -> None:
    _handles[PIPELINE_QUEUE] = DBOS.register_queue(PIPELINE_QUEUE, worker_concurrency=PIPELINE_WORKER_CONCURRENCY)
    _handles[GMAIL_SYNC_QUEUE] = DBOS.register_queue(GMAIL_SYNC_QUEUE, concurrency=1)
    _handles[TIMERS_QUEUE] = DBOS.register_queue(TIMERS_QUEUE, worker_concurrency=2)
    _handles[DOCUMENTS_QUEUE] = DBOS.register_queue(DOCUMENTS_QUEUE, partition_concurrency=1)
    _handles[CONCIERGE_QUEUE] = DBOS.register_queue(
        CONCIERGE_QUEUE,
        worker_concurrency=settings.concierge_worker_concurrency,
        polling_interval_sec=CONCIERGE_POLL_SECONDS,
    )


def _handle(name: str) -> Queue:
    try:
        return _handles[name]
    except KeyError as exc:
        raise RuntimeError(f"queue {name!r} not registered (the worker registers queues at launch)") from exc


def pipeline_queue() -> Queue:
    return _handle(PIPELINE_QUEUE)


def gmail_sync_queue() -> Queue:
    return _handle(GMAIL_SYNC_QUEUE)


def documents_queue() -> Queue:
    return _handle(DOCUMENTS_QUEUE)


def timers_queue() -> Queue:
    return _handle(TIMERS_QUEUE)


def concierge_queue() -> Queue:
    return _handle(CONCIERGE_QUEUE)
