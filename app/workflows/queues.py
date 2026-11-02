"""DBOS queues. Registered (persisted to the system DB) after launch; handles kept for workflow bodies.

Workflow bodies use these module-level handles instead of `DBOS.retrieve_queue`, so they do no system-DB reads.

The `concierge` queue (Super Agent turns, spec amendment 2026-10-22) keeps chat turns from waiting behind pipeline
work. Its worker polls every `CONCIERGE_POLL_SECONDS` instead of DBOS's default 1 s: each poll is one dequeue
transaction (plus a config reload) on the system database per worker, about 8 small queries/s per worker. DBOS
(3.2.0) accepts any positive interval and backs off on its own under contention (doubling up to 120 s, then easing
back), so 0.25 s is the short end that stays cheap; a turn waits at most about a quarter second to be picked up when a
slot is free.
At most `Settings.concierge_worker_concurrency` turns run at once per worker (each is mostly a model call).

The `finance` queue (M11 quote checker) runs decision-day snapshots and quote reviews, at most
`FINANCE_WORKER_CONCURRENCY` per worker; each run makes one model call (job_items or quote_reader; a recheck none).
"""

from dbos import DBOS, Queue

from app.core.settings import Settings
from app.core.workflow_names import (
    CONCIERGE_QUEUE,
    DOCUMENTS_QUEUE,
    FINANCE_QUEUE,
    GMAIL_SYNC_QUEUE,
    PIPELINE_QUEUE,
    TIMERS_QUEUE,
)

__all__ = [
    "CONCIERGE_POLL_SECONDS",
    "CONCIERGE_QUEUE",
    "DOCUMENTS_QUEUE",
    "FINANCE_QUEUE",
    "FINANCE_WORKER_CONCURRENCY",
    "GMAIL_SYNC_QUEUE",
    "PIPELINE_QUEUE",
    "PIPELINE_WORKER_CONCURRENCY",
    "concierge_queue",
    "documents_queue",
    "finance_queue",
    "gmail_sync_queue",
    "pipeline_queue",
]

# Per executor; keeps one VM from overrunning LLM rate limits. Combined ceiling: the `concierge` queue runs up to
# `Settings.concierge_worker_concurrency` (default 4) turns at the same time, so one worker can have up to 4 + 4 = 8
# model calls in flight (a turn makes one planner call, plus one owner_qa call only without a usable reply). The
# `finance` queue adds up to `FINANCE_WORKER_CONCURRENCY` (2) more, so 4 + 4 + 2 = 10 in all. Size the provider rate
# limit, or lower any of these numbers, for that total.
PIPELINE_WORKER_CONCURRENCY = 4
FINANCE_WORKER_CONCURRENCY = 2
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
    _handles[FINANCE_QUEUE] = DBOS.register_queue(FINANCE_QUEUE, worker_concurrency=FINANCE_WORKER_CONCURRENCY)


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


def finance_queue() -> Queue:
    return _handle(FINANCE_QUEUE)
