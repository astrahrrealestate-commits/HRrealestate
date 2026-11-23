"""Cancel BRIXX workflows that an older deploy left behind.

DBOS only runs and recovers workflows of its own application version, and the version is a hash of the workflow source
(ADR 0001), so a deploy that changes workflow code strands whatever the previous version had queued or running. For
BRIXX that is harmful, not just untidy: a stranded PENDING download holds the single slot of the `brixx_documents`
queue (concurrency 1) for good, and a stranded ENQUEUED one shares its deterministic id with the claim the next sync
would enqueue, so the download never runs. Everything BRIXX does is re-derived from Postgres by the next 15-minute sync,
so cancelling the leftovers loses nothing. Only workflows of another version that have not moved for
`STRANDED_AFTER` are touched: a rolling deploy's old tasks keep finishing their own work.
"""

from collections.abc import Sequence
from datetime import timedelta
from typing import Protocol

from dbos import DBOS

from app.core.logging import get_logger
from app.core.workflow_names import BRIXX_DOCUMENTS_QUEUE, BRIXX_QUEUE

log = get_logger(__name__)

STRANDED_AFTER = timedelta(minutes=30)
MAX_CANCELLED = 1000  # per sync: a first run after a long gap cleans up over a few ticks


class _Listed(Protocol):
    workflow_id: str
    app_version: str | None
    created_at: int | None
    updated_at: int | None


def stranded_ids(workflows: Sequence[_Listed], current_version: str, now_ms: int) -> list[str]:
    """Ids of workflows of another application version, untouched for `STRANDED_AFTER`."""
    cutoff = now_ms - int(STRANDED_AFTER.total_seconds() * 1000)
    return [
        w.workflow_id
        for w in workflows
        if w.app_version and w.app_version != current_version and (w.updated_at or w.created_at or 0) < cutoff
    ][:MAX_CANCELLED]


def reap_stranded(now_ms: int) -> int:
    """Cancel the stranded BRIXX workflows; returns how many. Needs a launched DBOS."""
    found = DBOS.list_workflows(
        status=["PENDING", "ENQUEUED"],
        queue_name=[BRIXX_QUEUE, BRIXX_DOCUMENTS_QUEUE],
        limit=5 * MAX_CANCELLED,
        load_input=False,
        load_output=False,
    )
    ids = stranded_ids(found, DBOS.application_version, now_ms)
    if ids:
        DBOS.cancel_workflows(ids)
        log.warning("brixx.stranded_cancelled", count=len(ids), version=DBOS.application_version)
    return len(ids)
