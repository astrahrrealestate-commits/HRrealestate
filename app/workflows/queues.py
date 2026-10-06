"""DBOS queues. Registered (persisted to the system DB) by `register_queues()` during launch."""

from dbos import DBOS

PIPELINE_QUEUE = "pipeline"
PIPELINE_WORKER_CONCURRENCY = 4  # per executor; keeps one VM from overrunning LLM rate limits


def register_queues() -> None:
    DBOS.register_queue(PIPELINE_QUEUE, worker_concurrency=PIPELINE_WORKER_CONCURRENCY)
