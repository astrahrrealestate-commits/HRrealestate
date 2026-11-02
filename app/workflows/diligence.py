"""Due diligence wiring: `dd:{review_id}:{run_no}` reads each document of a review, then compiles the report.

Runs on the `documents` queue (partitioned by company, concurrency 1), so one company's reviews never overlap. The
review row is already in Postgres; every step is safe to retry (reads are cached per document and reader version,
the report and feed card are written once).
"""

from uuid import UUID

from dbos import DBOS, SetEnqueueOptions, SetWorkflowID

from app.core.logging import get_logger
from app.core.settings import get_settings
from app.core.workflow_names import DD_REVIEW, dd_workflow_id
from app.diligence import service
from app.diligence.framework import load_framework
from app.workflows import queues
from app.workflows.deps import get_engine
from app.workflows.retry import STEP_RETRY

log = get_logger(__name__)


@DBOS.step(name="diligence.begin", **STEP_RETRY)
def begin_step(company_id: str, review_id: str, run_no: int) -> list[str] | None:
    ids = service.begin_run(get_engine(), UUID(company_id), UUID(review_id), run_no)
    return None if ids is None else [str(i) for i in ids]


@DBOS.step(name="diligence.read", **STEP_RETRY)
def read_step(company_id: str, document_id: str) -> bool:
    return service.read_document(get_engine(), get_settings(), UUID(company_id), UUID(document_id))


@DBOS.step(name="diligence.compile", **STEP_RETRY)
def compile_step(company_id: str, review_id: str, run_no: int) -> str | None:
    settings, engine = get_settings(), get_engine()
    framework = load_framework(settings.dd_framework_path)
    today = service.company_today(engine, UUID(company_id))
    verdict = service.compile_review(engine, framework, UUID(company_id), UUID(review_id), run_no, today)
    return None if verdict is None else verdict.value


@DBOS.step(name="diligence.fail")
def fail_step(company_id: str, review_id: str, run_no: int, error: str) -> None:
    service.fail_review(get_engine(), UUID(company_id), UUID(review_id), run_no, error)


@DBOS.workflow(name=DD_REVIEW)
def dd_review_wf(company_id: str, review_id: str, run_no: int) -> str:
    document_ids = begin_step(company_id, review_id, run_no)
    if document_ids is None:
        return "stale"
    try:
        for document_id in document_ids:
            read_step(company_id, document_id)
        return compile_step(company_id, review_id, run_no) or "stale"
    except Exception as exc:
        log.error("diligence.failed", review_id=review_id, run_no=run_no, reason=type(exc).__name__)
        fail_step(company_id, review_id, run_no, f"{type(exc).__name__}: {exc}")
        return "failed"


def enqueue_review(company_id: str, review_id: str, run_no: int) -> None:
    """Call after the review row committed (deterministic id: a repeated enqueue is deduped by DBOS)."""
    with SetWorkflowID(dd_workflow_id(review_id, run_no)), SetEnqueueOptions(queue_partition_key=company_id):
        queues.documents_queue().enqueue(dd_review_wf, company_id, review_id, run_no)
