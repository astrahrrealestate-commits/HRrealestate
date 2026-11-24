"""Workflow and queue names shared by enqueuers (api, ingestion) and the worker that registers them.

Lives in core so lower layers can enqueue by name without importing app.workflows (layer contract).
"""

from uuid import UUID, uuid5

PIPELINE_QUEUE = "pipeline"
GMAIL_SYNC_QUEUE = "gmail_sync"  # concurrency 1: syncs never overlap, no DB locks held across Gmail calls
TIMERS_QUEUE = "timers"  # due timers never wait behind LLM pipeline work (their lease starts at claim)
DOCUMENTS_QUEUE = "documents"  # partitioned per company, concurrency 1: Drive folder creation never races
CONCIERGE_QUEUE = "concierge"  # Super Agent turns: never wait behind pipeline work; short poll interval
BRIXX_QUEUE = "brixx"  # BRIXX mirror table syncs: slow upstream, never competes with pipeline work
BRIXX_DOCUMENTS_QUEUE = "brixx_documents"  # BRIXX file downloads, one at a time: never delays the table syncs
FINANCE_QUEUE = "finance"  # price snapshots and quote reviews (M11): never wait behind pipeline work
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
BRIXX_DOWNLOAD_DOCUMENT = "brixx.download_document"
BRIXX_RECONCILE_ALL = "brixx.reconcile_all"
BRIXX_RECONCILE_TABLE = "brixx.reconcile_table"
BRIXX_MAP_DIRECTORY = "brixx.map_directory"
FINANCE_SNAPSHOT = "finance.snapshot"
FINANCE_QUOTE = "finance.quote"
FINANCE_RECHECK = "finance.recheck"
CHAT_SEND = "chat.send_message"
_FINANCE_REVIEW_NAMESPACE = UUID("6f1c2a52-3d4e-5b7a-9c1d-2e8f4a6b0c13")  # fixed forever: review ids derive from it


def exec_workflow_id(action_id: object, draft_version: object) -> str:
    """`exec:<action_id>:<draft_version>`: the one execution of an approved action version (same as its send key)."""
    return f"exec:{action_id}:{draft_version}"


def chat_workflow_id(company_id: object, client_msg_id: object) -> str:
    """`chat:<company_id>:<client_msg_id>`: the one send of an owner-typed WhatsApp message (also its `sends` key)."""
    return f"chat:{company_id}:{client_msg_id}"


def reorg_workflow_id(plan_id: object) -> str:
    """`drive:reorg:<plan_id>`: the one application of an approved Drive reorganisation plan."""
    return f"drive:reorg:{plan_id}"


def brixx_run_workflow_id(run_id: object, table: str) -> str:
    """`brixx:<run_id>:<table>`: the one sync of a table within a run; a repeated enqueue is deduplicated by DBOS."""
    return f"brixx:{run_id}:{table}"


def brixx_document_workflow_id(
    company_id: object, document_id: int, version: str, attempt: int, app_version: str = ""
) -> str:
    """`brixxdoc:<company_id>:<document_id>:<version>:<attempt>:<app version>`: one download attempt of one version.

    A repeated enqueue (the next sync while the download is still queued) is deduplicated by DBOS; a failed version
    is claimed again with the next attempt number, so it gets a new workflow. The application version is part of the
    id so that a workflow an older deploy left queued (which the new version can never run) does not swallow the
    enqueue of the same claim.
    """
    return f"brixxdoc:{company_id}:{document_id}:{version}:{attempt}:{app_version[:8]}"


def brixx_reconcile_workflow_id(run_id: object, table: str) -> str:
    """`brixxrec:<run_id>:<table>`: the one reconcile of a table within a reconcile run."""
    return f"brixxrec:{run_id}:{table}"


def brixx_map_workflow_id(run_id: object) -> str:
    """`brixxmap:<run_id>`: the one directory mapping after a sync or reconcile run."""
    return f"brixxmap:{run_id}"


def concierge_workflow_id(turn_id: object) -> str:
    """`concierge:<turn_id>`: one Super Agent run per turn; DBOS dedupes a repeated enqueue."""
    return f"concierge:{turn_id}"


def finance_snapshot_workflow_id(action_id: object) -> str:
    """`fin:snap:<action_id>`: the one decision-day snapshot of an approved request_contractor action."""
    return f"fin:snap:{action_id}"


def finance_quote_workflow_id(message_id: object) -> str:
    """`fin:quote:<message_id>`: the one quote review of a contractor message."""
    return f"fin:quote:{message_id}"


def finance_recheck_workflow_id(quote_id: object, n: int) -> str:
    """`fin:recheck:<quote_id>:<n>`: the n-th recheck of a stored quote."""
    return f"fin:recheck:{quote_id}:{n}"


def finance_review_id(quote_id: object, n: int) -> UUID:
    """The review id of the n-th recheck of a quote: the same on every retry, so a retried step never adds a row."""
    return uuid5(_FINANCE_REVIEW_NAMESPACE, f"{quote_id}:{n}")


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
