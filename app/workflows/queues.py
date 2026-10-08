"""DBOS queues. Registered (persisted to the system DB) after launch; handles kept for workflow bodies.

Workflow bodies use these module-level handles instead of `DBOS.retrieve_queue`, so they do no system-DB reads.
"""

from dbos import DBOS, Queue

from app.core.workflow_names import DOCUMENTS_QUEUE, GMAIL_SYNC_QUEUE, PIPELINE_QUEUE, TIMERS_QUEUE

__all__ = [
    "DOCUMENTS_QUEUE",
    "GMAIL_SYNC_QUEUE",
    "PIPELINE_QUEUE",
    "PIPELINE_WORKER_CONCURRENCY",
    "documents_queue",
    "gmail_sync_queue",
    "pipeline_queue",
]

PIPELINE_WORKER_CONCURRENCY = 4  # per executor; keeps one VM from overrunning LLM rate limits
_handles: dict[str, Queue] = {}


def register_queues() -> None:
    _handles[PIPELINE_QUEUE] = DBOS.register_queue(PIPELINE_QUEUE, worker_concurrency=PIPELINE_WORKER_CONCURRENCY)
    _handles[GMAIL_SYNC_QUEUE] = DBOS.register_queue(GMAIL_SYNC_QUEUE, concurrency=1)
    _handles[TIMERS_QUEUE] = DBOS.register_queue(TIMERS_QUEUE, worker_concurrency=2)
    _handles[DOCUMENTS_QUEUE] = DBOS.register_queue(DOCUMENTS_QUEUE, partition_concurrency=1)


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
