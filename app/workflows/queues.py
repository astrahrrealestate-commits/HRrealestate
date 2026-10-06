"""DBOS queues. Registered (persisted to the system DB) by `register_queues()` during launch."""

from dbos import DBOS

from app.core.workflow_names import PIPELINE_QUEUE

__all__ = ["PIPELINE_QUEUE", "PIPELINE_WORKER_CONCURRENCY", "register_queues"]
PIPELINE_WORKER_CONCURRENCY = 4  # per executor; keeps one VM from overrunning LLM rate limits


def register_queues() -> None:
    DBOS.register_queue(PIPELINE_QUEUE, worker_concurrency=PIPELINE_WORKER_CONCURRENCY)
