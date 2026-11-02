"""Running a review: read each document once (cached), then compile the report and post the feed card.

Every function takes the engine and does its own short transaction, so each is safe as a DBOS step. The model reads
text into quoted claims (`dd_reader`); everything after that is the pure engine.
"""

from datetime import UTC, date, datetime
from uuid import UUID
from zoneinfo import ZoneInfo

from pydantic import ValidationError
from sqlalchemy import Engine, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.channels.dashboard.feed import stored_key
from app.contracts import DocType
from app.contracts.diligence import DDDocRead
from app.contracts.diligence_report import DDVerdict
from app.core.errors import NotFoundError
from app.core.settings import Settings
from app.db.enums import DDReviewStatus, FeedKind
from app.db.models import AttachmentRow, Company, DDDocumentRead, DDReview, DDReviewDocument, DocumentRow, OwnerFeed
from app.diligence.engine import screen
from app.diligence.framework import Framework
from app.diligence.inputs import DocInput
from app.diligence.summary import feed_payload
from app.diligence.verify import verify_read
from app.llm.agents.dd_reader import DD_READER, MAX_DOCUMENT_CHARS, READER_VERSION, dd_reader_prompt
from app.llm.calls import CallContext, run_agent


def company_today(engine: Engine, company_id: UUID) -> date:
    """Today in the company's own timezone: the date document ages are measured against."""
    with Session(engine) as session:
        tz = session.scalar(select(Company.timezone).where(Company.id == company_id))
    return datetime.now(ZoneInfo(tz or "UTC")).date()


def begin_run(engine: Engine, company_id: UUID, review_id: UUID, run_no: int) -> list[UUID] | None:
    """Mark the run started and return the document ids; None when the run is stale (restarted) or already done."""
    with Session(engine) as session, session.begin():
        review = session.scalar(
            select(DDReview).where(DDReview.company_id == company_id, DDReview.id == review_id).with_for_update()
        )
        if review is None:
            raise NotFoundError("review not found")
        if review.run_no != run_no or review.status in (DDReviewStatus.done, DDReviewStatus.failed):
            return None
        review.status = DDReviewStatus.running
        return list(
            session.scalars(
                select(DDReviewDocument.document_id)
                .where(DDReviewDocument.company_id == company_id, DDReviewDocument.review_id == review_id)
                .order_by(DDReviewDocument.created_at, DDReviewDocument.id)
            )
        )


def _source(session: Session, company_id: UUID, document_id: UUID) -> tuple[str, str] | None:
    """(filename, text) of a document that may be sent to the model, else None. Identity documents are never read
    (ADR 0007) and a document the injection scan flagged is not sent either."""
    row = session.execute(
        select(DocumentRow, AttachmentRow.extracted_text)
        .join(AttachmentRow, AttachmentRow.id == DocumentRow.attachment_id)
        .where(DocumentRow.company_id == company_id, DocumentRow.id == document_id)
    ).first()
    if row is None:
        raise NotFoundError("document not found")
    doc, extracted = row
    text = extracted or ""
    if doc.doc_type == DocType.id_document.value or doc.suspicious or not text.strip():
        return None
    return doc.file_name, text


def read_document(engine: Engine, settings: Settings, company_id: UUID, document_id: UUID) -> bool:
    """Read the document with `dd_reader` unless a verified read by this reader version already exists. True when a
    read is stored afterwards."""
    with Session(engine) as session:
        cached = session.scalar(
            select(DDDocumentRead.id).where(
                DDDocumentRead.company_id == company_id,
                DDDocumentRead.document_id == document_id,
                DDDocumentRead.reader_version == READER_VERSION,
            )
        )
        source = None if cached else _source(session, company_id, document_id)
    if cached:
        return True
    if source is None:
        return False
    filename, text = source
    ctx = CallContext(company_id=company_id, purpose="dd_reader")
    result = run_agent(engine, settings, DD_READER, dd_reader_prompt(filename, text), ctx)
    read, dropped = verify_read(result.output, text[:MAX_DOCUMENT_CHARS])
    with Session(engine) as session, session.begin():
        session.execute(
            insert(DDDocumentRead)
            .values(
                company_id=company_id, document_id=document_id, reader_version=READER_VERSION,
                read=read.model_dump(mode="json"), unverified=dropped,
            )
            .on_conflict_do_nothing(constraint="uq_dd_document_reads_company_id_document_id_reader_version")
        )  # fmt: skip
    return True


def _doc_inputs(session: Session, company_id: UUID, review_id: UUID) -> tuple[list[DocInput], int]:
    rows = session.execute(
        select(DocumentRow.id, DocumentRow.title, DDDocumentRead.read, DDDocumentRead.unverified)
        .join(DDReviewDocument, DDReviewDocument.document_id == DocumentRow.id)
        .outerjoin(
            DDDocumentRead,
            (DDDocumentRead.document_id == DocumentRow.id)
            & (DDDocumentRead.company_id == company_id)
            & (DDDocumentRead.reader_version == READER_VERSION),
        )
        .where(DDReviewDocument.company_id == company_id, DDReviewDocument.review_id == review_id)
        .order_by(DDReviewDocument.created_at, DDReviewDocument.id)
    ).all()
    docs, unverified = [], 0
    for doc_id, title, raw, dropped in rows:
        docs.append(DocInput(document_id=doc_id, title=title, read=_parse(raw)))
        unverified += dropped or 0
    return docs, unverified


def _parse(raw: dict[str, object] | None) -> DDDocRead | None:
    if raw is None:
        return None
    try:
        return DDDocRead.model_validate(raw)
    except ValidationError:
        return None  # a stored read from an older contract: treated as unreadable, not a crash


def compile_review(
    engine: Engine, framework: Framework, company_id: UUID, review_id: UUID, run_no: int, today: date
) -> DDVerdict | None:
    """Build and store the report, and post the feed card once. None when the run is stale. Idempotent."""
    with Session(engine) as session, session.begin():
        review = session.scalar(
            select(DDReview).where(DDReview.company_id == company_id, DDReview.id == review_id).with_for_update()
        )
        if review is None:
            raise NotFoundError("review not found")
        if review.run_no != run_no:
            return None
        if review.status is DDReviewStatus.done:
            return review.verdict
        docs, unverified = _doc_inputs(session, company_id, review_id)
        report = screen(framework, review.property_kind, docs, today, unverified=unverified)
        review.report, review.verdict = report.model_dump(mode="json"), report.verdict
        review.framework_version, review.status = report.framework_version, DDReviewStatus.done
        review.error, review.completed_at = None, datetime.now(UTC)
        session.execute(
            insert(OwnerFeed)
            .values(
                company_id=company_id, idempotency_key=stored_key(company_id, f"dd:{review_id}:{run_no}"),
                kind=FeedKind.dd_report, ref_id=review_id, payload=feed_payload(review_id, review.title, report),
            )
            .on_conflict_do_nothing(index_elements=["idempotency_key"])
        )  # fmt: skip
        return report.verdict


def fail_review(engine: Engine, company_id: UUID, review_id: UUID, run_no: int, error: str) -> None:
    with Session(engine) as session, session.begin():
        review = session.scalar(
            select(DDReview).where(DDReview.company_id == company_id, DDReview.id == review_id).with_for_update()
        )
        if review is not None and review.run_no == run_no and review.status is not DDReviewStatus.done:
            review.status, review.error = DDReviewStatus.failed, error[:500]
