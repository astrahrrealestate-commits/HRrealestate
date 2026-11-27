"""BRIXX document downloads: after `PRG_DOCUMENT` syncs, one queued `brixx.download_document` per unsettled version.

`enqueue_document_downloads` runs inside the table's sync workflow: a step claims up to `MAX_CLAIMS` versions
(commits them as `pending`, Postgres before work), then the body enqueues one workflow per claim with the id
`brixxdoc:<company>:<document>:<version>:<attempt>:<app version>` on the `brixx_documents` queue (concurrency 3).
The rest of a large backlog is claimed by later syncs, so every workflow stays short.

Workflow bodies only sequence steps. The download step is retry-safe: a settled version is not downloaded again and
equal bytes map to one object and one row. 401/403 settles the version as `forbidden`. `BrixxAuthError` and
`BrixxNotFoundError` (retrying cannot help either) fail after one attempt; any other error is retried by DBOS. Once
either path is exhausted, the version is recorded `failed` (class name only) and claimed again on a later sync until
`MAX_ATTEMPTS`.
"""

from typing import Any
from uuid import UUID

import sqlalchemy as sa
from dbos import DBOS, SetWorkflowID
from sqlalchemy.orm import Session

from app.core.logging import get_logger
from app.core.workflow_names import BRIXX_DOWNLOAD_DOCUMENT, brixx_document_workflow_id
from app.db.enums import BrixxDocumentStatus
from app.directory.brixx.document_candidates import candidates_query
from app.directory.brixx.document_state import claim_versions, record_unstored
from app.directory.brixx.documents import download_version
from app.directory.brixx.schema import build_table
from app.ingestion.process import is_transient
from app.workflows import queues
from app.workflows.brixx_common import BRIXX_RETRY, FAILED, brixx_retryable, error_name, info_from_json
from app.workflows.brixx_library import index_backlog, index_brixx_document, unindexed_version
from app.workflows.deps import brixx_api, get_deps, get_embedder, get_engine, get_extractor

log = get_logger(__name__)

MAX_CLAIMS = 600  # per sync of PRG_DOCUMENT (every 15 min): bounds the step output and the enqueue loop


def download_retryable(exc: BaseException) -> bool:
    """BRIXX/database errors as for the table sync, plus transient storage and network errors."""
    return brixx_retryable(exc) or is_transient(exc)


DOWNLOAD_RETRY: dict[str, Any] = {**BRIXX_RETRY, "should_retry": download_retryable}


@DBOS.step(name="brixx.claim_documents", **BRIXX_RETRY)
def claim_documents_step(company_id: str, info: dict[str, Any]) -> list[list[Any]]:
    """Commit up to `MAX_CLAIMS` unsettled versions as `pending`; returns `[document_id, version, attempt]` each."""
    cid = UUID(company_id)
    table = build_table(info_from_json(info), sa.MetaData())
    with Session(get_engine()) as session:
        found = session.execute(candidates_query(table, cid, MAX_CLAIMS)).all()
        claims = claim_versions(session, cid, [(int(doc), str(version)) for doc, version in found])
        session.commit()
    log.info("brixx.documents_claimed", company_id=company_id, claimed=len(claims))
    return [[c.document_id, c.version, c.attempt] for c in claims]


def enqueue_document_downloads(company_id: str, info: dict[str, Any]) -> int:
    """Workflow-body helper: claim, then enqueue one deterministic download workflow per claimed version."""
    claims = claim_documents_step(company_id, info)
    for document_id, version, attempt in claims:
        with SetWorkflowID(
            brixx_document_workflow_id(company_id, document_id, version, attempt, DBOS.application_version)
        ):
            queues.brixx_documents_queue().enqueue(download_document, company_id, document_id, version)
    return len(claims)


@DBOS.step(name="brixx.fetch_document", **DOWNLOAD_RETRY)
def download_step(company_id: str, document_id: int, version: str) -> str:
    with Session(get_engine()) as session:
        status = download_version(session, brixx_api(), get_deps().storage, UUID(company_id), document_id, version)
    return status.value


@DBOS.step(name="brixx.document_failed", **BRIXX_RETRY)
def failed_step(company_id: str, document_id: int, version: str, error: str) -> None:
    with Session(get_engine()) as session:
        record_unstored(session, UUID(company_id), document_id, version, BrixxDocumentStatus.failed, error)
        session.commit()


@DBOS.step(name="brixx.index_document")  # no retries: a failed index never holds the download workflow
def index_document_step(company_id: str, document_id: int) -> bool:
    """The newest stored version of the document into the library (M13); idempotent."""
    cid = UUID(company_id)
    newest = unindexed_version(get_engine(), cid, document_id)
    if newest is None:
        return False
    return index_brixx_document(get_engine(), get_deps().storage, get_extractor(), get_embedder(), cid, newest)


@DBOS.step(name="brixx.index_backlog")  # no retries: the next sync picks the backlog up
def index_backlog_step(company_id: str) -> int:
    """Stored documents not in the library yet, a bounded batch per sync (the files downloaded before M13 too)."""
    return index_backlog(get_engine(), get_deps().storage, get_extractor(), get_embedder(), UUID(company_id))


@DBOS.workflow(name=BRIXX_DOWNLOAD_DOCUMENT)
def download_document(company_id: str, document_id: int, version: str) -> str:
    """Download one document version. Returns `stored`, `forbidden` or `failed:<ErrorClass>`; never raises for a
    failed download, so DBOS does not rerun the workflow and the failure stays visible in `brixx_documents`."""
    try:
        status = download_step(company_id, document_id, version)
    except Exception as exc:
        name = error_name(exc)
        log.warning("brixx.document_failed", company_id=company_id, document_id=document_id, error=name)
        failed_step(company_id, document_id, version, name)
        return FAILED + name
    if status == BrixxDocumentStatus.stored.value:
        try:
            index_document_step(company_id, document_id)  # the text reaches dossiers and Astra right away
        except Exception as exc:  # the next sync's backlog step indexes it
            log.warning("brixx.index_failed", company_id=company_id, document_id=document_id, error=error_name(exc))
    return status
