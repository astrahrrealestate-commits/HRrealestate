"""DBOS system-table retention (M8 carry-over): the minute timer sweep alone writes ~1,440 workflow rows a day.

Daily, terminal workflows (finished, failed or cancelled) older than `RETENTION_DAYS` are deleted with DBOS's own
garbage collector, which also removes their steps, events and payloads in batches and holds a retention lock so two
rounds never overlap. Running or enqueued workflows are never touched. Deleting an old workflow id weakens no
"do once" guarantee: every one is also backed by a unique constraint in our tables (CLAUDE.md invariant 2).
"""

from datetime import datetime, timedelta
from typing import Any

from dbos import DBOS

from app.core.logging import get_logger

log = get_logger(__name__)
RETENTION_DAYS = 30  # long enough to debug a month of `make workflows`; Postgres backups keep older history


def cutoff_ms(scheduled_time: datetime) -> int:
    return int((scheduled_time - timedelta(days=RETENTION_DAYS)).timestamp() * 1000)


@DBOS.step(name="maintenance.dbos_gc")
def gc_step(cutoff_epoch_ms: int) -> None:
    # dbos 3.2 exposes the collector only via its internal command module (used by DBOS Conductor); kept to this
    # one call so a DBOS upgrade that moves it fails here, in tests/integration/test_maintenance.py.
    from dbos._dbos import _get_dbos_instance
    from dbos._workflow_commands import garbage_collect

    garbage_collect(_get_dbos_instance(), cutoff_epoch_timestamp_ms=cutoff_epoch_ms, rows_threshold=None)
    log.info("maintenance.dbos_gc.done", cutoff_epoch_ms=cutoff_epoch_ms)


@DBOS.workflow(name="maintenance.dbos_retention")
def dbos_retention(scheduled_time: datetime, context: Any) -> None:
    """Daily schedule. The cutoff comes from the scheduled time (an input), so the workflow stays deterministic."""
    gc_step(cutoff_ms(scheduled_time))
