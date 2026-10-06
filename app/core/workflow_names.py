"""Workflow and queue names shared by enqueuers (api, ingestion) and the worker that registers them.

Lives in core so lower layers can enqueue by name without importing app.workflows (layer contract).
"""

PIPELINE_QUEUE = "pipeline"
GMAIL_SYNC_QUEUE = "gmail_sync"  # concurrency 1: syncs never overlap, no DB locks held across Gmail calls
PROCESS_EVENT = "ingest.process_event"
GMAIL_SYNC = "ingest.gmail_sync"
OWNER_REPLY = "owner.reply"
PIPELINE_ENTRY = "pipeline.entry"


def event_workflow_id(raw_event_id: object, attempt: int = 0) -> str:
    """`evt:<id>` for the first run; requeues of retryable failures get `evt:<id>:r<n>`."""
    return f"evt:{raw_event_id}" if attempt == 0 else f"evt:{raw_event_id}:r{attempt}"


def stale_event_workflow_id(raw_event_id: object, now: object) -> str:
    """Rerun of an event stranded in `pending`; one per hour at most (`now` is a datetime)."""
    return f"evt:{raw_event_id}:p{now:%Y%m%d%H}"
