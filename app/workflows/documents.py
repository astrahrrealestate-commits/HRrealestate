"""Document filing wiring (#9): `doc:{attachment_id}` after linking, `doc:{attachment_id}:owner:<choice>` on a tap.

Runs on the `documents` queue, partitioned by company with concurrency 1, so two first-ever filings of one company
never race to create the same Drive folder.
"""

from typing import Any
from uuid import UUID

from dbos import DBOS, SetEnqueueOptions, SetWorkflowID
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.contracts import DocType
from app.core.logging import get_logger
from app.core.settings import get_settings
from app.core.workflow_names import DOC_SKIP, FILE_DOCUMENT
from app.db.models import AttachmentRow, DocumentRow
from app.ingestion.process import is_transient
from app.llm.calls import is_transient as llm_transient
from app.owner.cards import document_review_key, document_review_payload
from app.pipeline.document_embed import embed_document
from app.pipeline.document_links import link_document
from app.pipeline.documents import file_document, skip_document
from app.storage.drive import is_transient as drive_transient
from app.workflows import queues
from app.workflows.deps import get_deps, get_drive, get_embedder, get_engine, get_extractor
from app.workflows.owner_notify import send_owner_message
from app.workflows.retry import STEP_RETRY

SKIP = DOC_SKIP


log = get_logger(__name__)


def _retryable(exc: BaseException) -> bool:
    return drive_transient(exc) or llm_transient(exc) or is_transient(exc)


DRIVE_STEP_RETRY: dict[str, Any] = {
    "retries_allowed": True,
    "max_attempts": 6,
    "interval_seconds": 5.0,
    "backoff_rate": 2.0,
    "should_retry": _retryable,
}


@DBOS.step(name="documents.file", **DRIVE_STEP_RETRY)
def file_step(company_id: str, attachment_id: str, owner_choice: str | None) -> str:
    doc_type = DocType(owner_choice) if owner_choice else None
    status = file_document(
        get_engine(),
        get_settings(),
        get_deps().storage,
        get_drive(),
        UUID(company_id),
        UUID(attachment_id),
        owner_doc_type=doc_type,
        extractor=get_extractor(),
    )
    return status.value


@DBOS.step(name="documents.link")
def link_step(company_id: str, attachment_id: str) -> int:
    """Link the document to its people, unit, lease and case. Idempotent; runs for every outcome except `skipped`."""
    return len(link_document(get_engine(), UUID(company_id), UUID(attachment_id)).links)


@DBOS.step(name="documents.embed")
def embed_step(company_id: str, attachment_id: str) -> int:
    """Vectors for the document's chunks and summary; safe to repeat. A provider problem is logged, not raised: the
    document is filed and retrievable by words, and the backfill refills the vectors later."""
    with Session(get_engine()) as session:
        doc_id = session.scalar(
            select(DocumentRow.id).where(
                DocumentRow.attachment_id == UUID(attachment_id), DocumentRow.company_id == UUID(company_id)
            )
        )
    if doc_id is None:
        return 0
    try:
        return embed_document(get_engine(), get_embedder(), UUID(company_id), doc_id)
    except SQLAlchemyError:
        raise  # a database problem is a real failure
    except Exception as exc:
        log.error("documents.embed_failed", attachment_id=attachment_id, reason=type(exc).__name__)
        return 0


@DBOS.step(name="documents.skip")
def skip_step(company_id: str, attachment_id: str) -> str:
    return skip_document(get_engine(), UUID(company_id), UUID(attachment_id)).value


@DBOS.step(name="documents.review_card", **STEP_RETRY)  # a provider blip must not lose the card
def review_card_step(company_id: str, attachment_id: str) -> bool:
    with Session(get_engine()) as session:
        row = session.execute(
            select(DocumentRow, AttachmentRow.filename, AttachmentRow.mime_type)
            .join(AttachmentRow, AttachmentRow.id == DocumentRow.attachment_id)
            .where(DocumentRow.company_id == UUID(company_id), DocumentRow.attachment_id == UUID(attachment_id))
        ).first()
    if row is None:
        return False
    doc, filename, mime = row
    build = document_review_payload(UUID(attachment_id), filename or mime, doc.doc_type, doc.title)
    return send_owner_message(company_id, document_review_key(attachment_id), build)


@DBOS.workflow(name=FILE_DOCUMENT)
def file_document_wf(company_id: str, attachment_id: str, owner_choice: str | None) -> str:
    if owner_choice == SKIP:
        return skip_step(company_id, attachment_id)
    status = file_step(company_id, attachment_id, owner_choice)
    if status != "skipped":
        link_step(company_id, attachment_id)
    if status == "review" and owner_choice is None:
        review_card_step(company_id, attachment_id)
    if status != "skipped":
        embed_step(company_id, attachment_id)  # last: a provider outage never delays the owner's review card
    return status


def enqueue_filing(company_id: str, attachment_id: str, owner_choice: str | None = None) -> None:
    """Call from a workflow (deterministic id): one filing per attachment, one rerun per owner choice."""
    workflow_id = f"doc:{attachment_id}" if owner_choice is None else f"doc:{attachment_id}:owner:{owner_choice}"
    with SetWorkflowID(workflow_id), SetEnqueueOptions(queue_partition_key=company_id):
        queues.documents_queue().enqueue(file_document_wf, company_id, attachment_id, owner_choice)
