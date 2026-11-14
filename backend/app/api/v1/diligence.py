"""Due Diligence Lite API: start a screening of chosen documents, list reviews, read a report, rerun.

Company-scoped through the session principal; writes need the CSRF header; foreign or missing ids answer the same 404.
Report text comes from documents (titles, quotes), so links, e-mail addresses and IBANs are stripped from it.
"""

from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import AwareDatetime, BaseModel, Field
from sqlalchemy import Engine

from app.api.deps import WorkflowClient, get_engine, get_settings_dep, get_workflow_client
from app.api.v1 import enqueue
from app.api.v1.access import require_section
from app.api.v1.auth import Principal, require_csrf, require_principal
from app.api.v1.ratelimit import decision_limit
from app.contracts.diligence import DDPropertyKind
from app.contracts.diligence_report import DDReport, DDVerdict
from app.core.errors import DiligenceRequestError, NotFoundError
from app.core.settings import Settings
from app.db.enums import DDReviewStatus
from app.diligence import repo
from app.pipeline.document_qa import strip_risky

router = APIRouter(
    prefix="/diligence", tags=["diligence"], dependencies=[Depends(require_section("properties", also=("inbox",)))]
)
NOT_FOUND = "not found"
Owner = Annotated[Principal, Depends(require_principal)]
Engine_ = Annotated[Engine, Depends(get_engine)]
Settings_ = Annotated[Settings, Depends(get_settings_dep)]
WorkflowClient_ = Annotated[WorkflowClient, Depends(get_workflow_client)]
WRITE = [Depends(require_csrf), Depends(decision_limit)]


class ReviewIn(BaseModel):
    title: Annotated[str, Field(min_length=1, max_length=200)]
    property_kind: DDPropertyKind
    document_ids: Annotated[list[UUID], Field(min_length=1, max_length=200)]
    unit_id: UUID | None = None


class RerunIn(BaseModel):
    document_ids: Annotated[list[UUID], Field(min_length=1, max_length=200)] | None = None  # None: same documents


class ReviewOut(BaseModel):
    id: UUID
    title: str
    property_kind: DDPropertyKind
    unit_id: UUID | None
    status: DDReviewStatus
    run_no: int
    verdict: DDVerdict | None
    framework_version: str | None
    error: str | None
    document_ids: list[UUID]
    created_at: AwareDatetime
    completed_at: AwareDatetime | None


class ReviewDetailOut(ReviewOut):
    report: DDReport | None  # null until the run is done


class RunOut(BaseModel):
    id: UUID
    run_no: int


_TEXT_KEYS = frozenset({"title", "quote", "value", "summary", "difference", "note", "label", "why"})


def _clean(node: Any, key: str | None = None) -> Any:
    """`strip_risky` on the free-text fields only: ids and codes stay untouched (an IBAN pattern can match a UUID)."""
    if isinstance(node, str):
        return strip_risky(node) if key in _TEXT_KEYS else node
    if isinstance(node, dict):
        return {k: _clean(v, k) for k, v in node.items()}
    if isinstance(node, list):
        return [_clean(v, key) for v in node]
    return node


def _out(v: repo.ReviewView) -> ReviewOut:
    return ReviewOut(
        id=v.id, title=strip_risky(v.title), property_kind=v.property_kind, unit_id=v.unit_id, status=v.status,
        run_no=v.run_no, verdict=v.verdict, framework_version=v.framework_version,
        error=strip_risky(v.error) if v.error else None, document_ids=v.document_ids, created_at=v.created_at,
        completed_at=v.completed_at,
    )  # fmt: skip


def _detail(v: repo.ReviewView) -> ReviewDetailOut:
    report = DDReport.model_validate(_clean(v.report.model_dump(mode="json"))) if v.report else None
    return ReviewDetailOut(**_out(v).model_dump(), report=report)


@router.post("/reviews", status_code=202, dependencies=WRITE)
def create(body: ReviewIn, who: Owner, engine: Engine_, settings: Settings_, client: WorkflowClient_) -> RunOut:
    """Start a screening. The review row is saved first, then the run is queued; poll `GET /reviews/{id}`."""
    try:
        review_id = repo.create_review(
            engine, who.company_id, title=body.title, kind=body.property_kind, document_ids=body.document_ids,
            unit_id=body.unit_id, max_documents=settings.dd_max_documents,
        )  # fmt: skip
    except NotFoundError:
        raise HTTPException(status_code=404, detail=NOT_FOUND) from None
    except DiligenceRequestError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None
    enqueue.enqueue_dd_review(client, who.company_id, review_id, 1)
    return RunOut(id=review_id, run_no=1)


@router.get("/reviews")
def list_all(who: Owner, engine: Engine_, limit: Annotated[int, Query(ge=1, le=50)] = 20) -> list[ReviewOut]:
    return [_out(v) for v in repo.list_reviews(engine, who.company_id, limit)]


@router.get("/reviews/{review_id}")
def read(review_id: UUID, who: Owner, engine: Engine_) -> ReviewDetailOut:
    try:
        return _detail(repo.get_review(engine, who.company_id, review_id))
    except NotFoundError:
        raise HTTPException(status_code=404, detail=NOT_FOUND) from None


@router.post("/reviews/{review_id}/rerun", status_code=202, dependencies=WRITE)
def rerun(
    review_id: UUID, body: RerunIn, who: Owner, engine: Engine_, settings: Settings_, client: WorkflowClient_
) -> RunOut:
    """Screen again (optionally with a different document set). Documents already read are not read again."""
    try:
        run_no = repo.restart_review(engine, who.company_id, review_id, body.document_ids, settings.dd_max_documents)
    except NotFoundError:
        raise HTTPException(status_code=404, detail=NOT_FOUND) from None
    except DiligenceRequestError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None
    enqueue.enqueue_dd_review(client, who.company_id, review_id, run_no)
    return RunOut(id=review_id, run_no=run_no)
