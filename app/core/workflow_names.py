"""Workflow and queue names shared by enqueuers (api, ingestion) and the worker that registers them.

Lives in core so lower layers can enqueue by name without importing app.workflows (layer contract).
"""

PIPELINE_QUEUE = "pipeline"
GMAIL_SYNC_QUEUE = "gmail_sync"  # concurrency 1: syncs never overlap, no DB locks held across Gmail calls
TIMERS_QUEUE = "timers"  # due timers never wait behind LLM pipeline work (their lease starts at claim)
DOCUMENTS_QUEUE = "documents"  # partitioned per company, concurrency 1: Drive folder creation never races
CONCIERGE_QUEUE = "concierge"  # Super Agent turns: never wait behind pipeline work; short poll interval
BRIXX_QUEUE = "brixx"  # BRIXX mirror table syncs: slow upstream, never competes with pipeline work
PROCESS_EVENT = "ingest.process_event"
GMAIL_SYNC = "ingest.gmail_sync"
OWNER_REPLY = "owner.reply"
PIPELINE_ENTRY = "pipeline.entry"
EXECUTE_ACTION = "actions.execute_action"
FILE_DOCUMENT = "documents.file_document"
REORG_PLAN = "documents.reorg_plan"
BACKFILL_DOCUMENTS = "documents.backfill"
CONCIERGE_TURN = "concierge.turn"
DD_REVIEW = "diligence.review"
BRIXX_SYNC_ALL = "brixx.sync_all"
BRIXX_SYNC_TABLE = "brixx.sync_table"


def exec_workflow_id(action_id: object, draft_version: object) -> str:
    """`exec:<action_id>:<draft_version>`: the one execution of an approved action version (same as its send key)."""
    return f"exec:{action_id}:{draft_version}"


def reorg_workflow_id(plan_id: object) -> str:
    """`drive:reorg:<plan_id>`: the one application of an approved Drive reorganisation plan."""
    return f"drive:reorg:{plan_id}"


def brixx_run_workflow_id(run_id: object, table: str) -> str:
    """`brixx:<run_id>:<table>`: the one sync of a table within a run; a repeated enqueue is deduplicated by DBOS."""
    return f"brixx:{run_id}:{table}"


def concierge_workflow_id(turn_id: object) -> str:
    """`concierge:<turn_id>`: one Super Agent run per turn; DBOS dedupes a repeated enqueue."""
    return f"concierge:{turn_id}"


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


DOC_SKIP = "skip"  # owner choice: do not file this attachment


def dd_workflow_id(review_id: object, run_no: int) -> str:
    """`dd:<review_id>:<run_no>`: one screening run; a rerun bumps `run_no`, a repeated enqueue is deduped."""
    return f"dd:{review_id}:{run_no}"
