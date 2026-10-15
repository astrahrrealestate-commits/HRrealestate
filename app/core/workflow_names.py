"""Workflow and queue names shared by enqueuers (api, ingestion) and the worker that registers them.

Lives in core so lower layers can enqueue by name without importing app.workflows (layer contract).
"""

PIPELINE_QUEUE = "pipeline"
GMAIL_SYNC_QUEUE = "gmail_sync"  # concurrency 1: syncs never overlap, no DB locks held across Gmail calls
TIMERS_QUEUE = "timers"  # due timers never wait behind LLM pipeline work (their lease starts at claim)
DOCUMENTS_QUEUE = "documents"  # partitioned per company, concurrency 1: Drive folder creation never races
PROCESS_EVENT = "ingest.process_event"
GMAIL_SYNC = "ingest.gmail_sync"
OWNER_REPLY = "owner.reply"
PIPELINE_ENTRY = "pipeline.entry"
EXECUTE_ACTION = "actions.execute_action"
FILE_DOCUMENT = "documents.file_document"


def event_workflow_id(raw_event_id: object) -> str:
    """`evt:<id>`: the first (and normally only) processing run of a raw event."""
    return f"evt:{raw_event_id}"


def requeue_workflow_id(raw_event_id: object, attempt: int, now: object) -> str:
    """Rerun of a retryable failure: attempt + hour (`now` is a datetime). A sweep running twice in one hour enqueues
    once; a rerun whose failure could not be recorded (attempts unchanged) is retried the next hour, never stuck."""
    return f"evt:{raw_event_id}:r{attempt}:{now:%Y%m%d%H}"


def stale_event_workflow_id(raw_event_id: object, now: object) -> str:
    """Rerun of an event stranded in `pending`; one per hour at most (`now` is a datetime)."""
    return f"evt:{raw_event_id}:p{now:%Y%m%d%H}"
