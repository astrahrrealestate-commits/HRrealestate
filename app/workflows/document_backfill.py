"""`documents:backfill:{company_id}`: read and link documents filed before M10, then propose one reorg plan."""

from uuid import UUID

from dbos import DBOS

from app.core.settings import get_settings
from app.core.workflow_names import BACKFILL_DOCUMENTS
from app.pipeline.document_backfill import backfill_document, unread_ids
from app.pipeline.drive_reorg import build_plan
from app.workflows.deps import get_deps, get_engine, get_extractor
from app.workflows.documents import DRIVE_STEP_RETRY

MAX_BATCHES = 25  # the workflow stays short; a rerun (new id) continues where this one stopped


@DBOS.step(name="documents.backfill_batch", **DRIVE_STEP_RETRY)
def batch_step(company_id: str) -> int:
    """Process up to a batch of unread documents; returns how many were handled (0 = done)."""
    engine, settings = get_engine(), get_settings()
    ids = unread_ids(engine, UUID(company_id))
    for attachment_id in ids:
        backfill_document(engine, settings, get_deps().storage, get_extractor(), UUID(company_id), attachment_id)
    return len(ids)


@DBOS.step(name="documents.backfill_plan")
def plan_step(company_id: str) -> str | None:
    plan = build_plan(get_engine(), UUID(company_id), "system")
    return str(plan) if plan else None


@DBOS.workflow(name=BACKFILL_DOCUMENTS)
def backfill_wf(company_id: str) -> str | None:
    for _ in range(MAX_BATCHES):
        if batch_step(company_id) == 0:
            break
    return plan_step(company_id)
