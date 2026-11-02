"""Reviews in Postgres: create, restart, read. Every query filters by `company_id` (invariant 4)."""

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from sqlalchemy import Engine, delete, select
from sqlalchemy.orm import Session

from app.contracts.diligence import DDPropertyKind
from app.contracts.diligence_report import DDReport, DDVerdict
from app.core.errors import DiligenceRequestError, NotFoundError
from app.db.enums import DDReviewStatus
from app.db.models import DDReview, DDReviewDocument, DocumentRow, Unit


@dataclass(frozen=True)
class ReviewView:
    id: UUID
    title: str
    property_kind: DDPropertyKind
    unit_id: UUID | None
    status: DDReviewStatus
    run_no: int
    verdict: DDVerdict | None
    framework_version: str | None
    report: DDReport | None
    error: str | None
    document_ids: list[UUID]
    created_at: datetime
    completed_at: datetime | None


def clean_ids(ids: list[UUID], max_documents: int) -> list[UUID]:
    unique = list(dict.fromkeys(ids))
    if not unique:
        raise DiligenceRequestError("choose at least one document")
    if len(unique) > max_documents:
        raise DiligenceRequestError(f"a review takes at most {max_documents} documents")
    return unique


def _check_documents(session: Session, company_id: UUID, ids: list[UUID]) -> None:
    found = set(
        session.scalars(select(DocumentRow.id).where(DocumentRow.company_id == company_id, DocumentRow.id.in_(ids)))
    )
    if found != set(ids):
        raise NotFoundError("document not found")


def _review(session: Session, company_id: UUID, review_id: UUID, *, lock: bool = False) -> DDReview:
    stmt = select(DDReview).where(DDReview.company_id == company_id, DDReview.id == review_id)
    review = session.scalar(stmt.with_for_update() if lock else stmt)
    if review is None:
        raise NotFoundError("review not found")
    return review


def create_review(
    engine: Engine, company_id: UUID, *, title: str, kind: DDPropertyKind, document_ids: list[UUID],
    unit_id: UUID | None, max_documents: int,
) -> UUID:  # fmt: skip
    ids = clean_ids(document_ids, max_documents)
    with Session(engine) as session, session.begin():
        _check_documents(session, company_id, ids)
        if (
            unit_id is not None
            and session.scalar(select(Unit.id).where(Unit.company_id == company_id, Unit.id == unit_id)) is None
        ):
            raise NotFoundError("unit not found")
        review = DDReview(company_id=company_id, title=title.strip(), property_kind=kind, unit_id=unit_id)
        session.add(review)
        session.flush()
        session.add_all(DDReviewDocument(company_id=company_id, review_id=review.id, document_id=d) for d in ids)
        return review.id


def restart_review(
    engine: Engine, company_id: UUID, review_id: UUID, document_ids: list[UUID] | None, max_documents: int
) -> int:
    """Bump `run_no` and reset to pending (optionally with a new document set); returns the new run number. Allowed in
    any state: a run still going finds its `run_no` stale and writes nothing, so a stuck review can always be rerun."""
    with Session(engine) as session, session.begin():
        review = _review(session, company_id, review_id, lock=True)
        if document_ids is not None:
            ids = clean_ids(document_ids, max_documents)
            _check_documents(session, company_id, ids)
            session.execute(
                delete(DDReviewDocument).where(
                    DDReviewDocument.company_id == company_id, DDReviewDocument.review_id == review_id
                )
            )
            session.add_all(DDReviewDocument(company_id=company_id, review_id=review_id, document_id=d) for d in ids)
        review.run_no += 1
        # the old run is stale from here on (its run_no no longer matches); nothing of it may be served as current
        review.status, review.error, review.completed_at = DDReviewStatus.pending, None, None
        review.report, review.verdict, review.framework_version = None, None, None
        return review.run_no


def _view(review: DDReview, document_ids: list[UUID]) -> ReviewView:
    report = DDReport.model_validate(review.report) if review.report else None
    return ReviewView(
        id=review.id, title=review.title, property_kind=review.property_kind, unit_id=review.unit_id,
        status=review.status, run_no=review.run_no, verdict=review.verdict,
        framework_version=review.framework_version, report=report, error=review.error, document_ids=document_ids,
        created_at=review.created_at, completed_at=review.completed_at,
    )  # fmt: skip


def _document_ids(session: Session, company_id: UUID, review_ids: list[UUID]) -> dict[UUID, list[UUID]]:
    rows = session.execute(
        select(DDReviewDocument.review_id, DDReviewDocument.document_id)
        .where(DDReviewDocument.company_id == company_id, DDReviewDocument.review_id.in_(review_ids))
        .order_by(DDReviewDocument.created_at, DDReviewDocument.id)
    )
    out: dict[UUID, list[UUID]] = {r: [] for r in review_ids}
    for review_id, document_id in rows:
        out[review_id].append(document_id)
    return out


def get_review(engine: Engine, company_id: UUID, review_id: UUID) -> ReviewView:
    with Session(engine) as session:
        review = _review(session, company_id, review_id)
        return _view(review, _document_ids(session, company_id, [review_id])[review_id])


def list_reviews(engine: Engine, company_id: UUID, limit: int) -> list[ReviewView]:
    with Session(engine) as session:
        reviews = session.scalars(
            select(DDReview).where(DDReview.company_id == company_id).order_by(DDReview.created_at.desc()).limit(limit)
        ).all()
        docs = _document_ids(session, company_id, [r.id for r in reviews])
        return [_view(r, docs[r.id]) for r in reviews]
