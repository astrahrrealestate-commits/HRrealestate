"""Workflow and queue names shared by enqueuers (api, ingestion) and the worker that registers them.

Lives in core so lower layers can enqueue by name without importing app.workflows (layer contract).
"""

PIPELINE_QUEUE = "pipeline"
PROCESS_EVENT = "ingest.process_event"
GMAIL_SYNC = "ingest.gmail_sync"
OWNER_REPLY = "owner.reply"
PIPELINE_ENTRY = "pipeline.entry"


def event_workflow_id(raw_event_id: object) -> str:
    return f"evt:{raw_event_id}"
