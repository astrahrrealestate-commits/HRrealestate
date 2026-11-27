"""Document library: search and filter, one document with its facts and links, and the owner's link fixes.

Read routes are company-scoped through the session principal. Snippets and summaries come from document text and are
returned as data. Writes (link, unlink) need the CSRF header; foreign ids answer the same 404 as missing ones.
"""

from datetime import UTC, date, datetime
from typing import Annotated, Any, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import AwareDatetime, BaseModel
from sqlalchemy import Engine
from sqlalchemy.orm import Session

from app.api.deps import WorkflowClient, get_embedder_dep, get_engine, get_workflow_client
from app.api.v1 import enqueue
from app.api.v1.access import require_admin, require_section
from app.api.v1.auth import Principal, require_csrf, require_principal
from app.api.v1.ratelimit import decision_limit
from app.core.errors import NotFoundError, PersonalDocumentError
from app.db.enums import DocLinkKind, DocumentStatus, ReorgItemStatus, ReorgPlanStatus
from app.llm.embeddings import TextEmbedder
from app.pipeline.document_links import set_link, set_reference
from app.pipeline.document_qa import strip_risky
from app.pipeline.document_search import DocDetail, DocFilter, DocHit, get_document, list_documents, search_documents
from app.pipeline.drive_reorg import PlanView, build_plan, decide_plan, latest_plan
from app.pipeline.rag import search_hybrid

router = APIRouter(tags=["documents"], dependencies=[Depends(require_section("inbox", also=("maintenance",)))])
NOT_FOUND = "not found"
PERSONAL_DOCUMENT = "a document of a person, their lease, unit or case cannot be a reference document"
Owner = Annotated[Principal, Depends(require_principal)]
Engine_ = Annotated[Engine, Depends(get_engine)]
Embedder_ = Annotated[TextEmbedder, Depends(get_embedder_dep)]
WorkflowClient_ = Annotated[WorkflowClient, Depends(get_workflow_client)]


class DocumentOut(BaseModel):
    id: UUID
    attachment_id: UUID | None  # None for a document indexed from BRIXX
    title: str
    doc_type: str
    status: DocumentStatus
    document_date: date | None
    summary: str | None
    snippet: str | None  # «highlighted» words from the best matching passage; untrusted text
    rank: float
    drive_url: str | None
    suspicious: bool
    created_at: AwareDatetime
    is_reference: bool = False


class LinkOut(BaseModel):
    kind: DocLinkKind
    ref_id: UUID
    label: str
    method: str  # message | case | fuzzy | lease | owner


class DocumentDetailOut(DocumentOut):
    file_name: str
    facts: dict[str, Any] | None  # parties, unit_hint, start_date, end_date, key_facts
    unresolved: list[str]  # names or addresses the document mentions that could not be linked
    links: list[LinkOut]
    chunk_count: int


class LinkIn(BaseModel):
    kind: DocLinkKind
    ref_id: UUID


class PlanItemOut(BaseModel):
    id: UUID
    document_id: UUID
    title: str
    from_folder: str
    to_folder: str
    from_name: str
    to_name: str
    reason: str
    status: ReorgItemStatus


class PlanOut(BaseModel):
    id: UUID
    status: ReorgPlanStatus
    created_by: str
    created_at: AwareDatetime
    items: list[PlanItemOut]


class PlanDecisionIn(BaseModel):
    approve: bool
    item_ids: list[UUID] | None = None  # approve only these items (the rest are rejected); None = all


class PlanCreatedOut(BaseModel):
    plan_id: UUID | None  # None: every document is already where it belongs, or already planned


class PlanStatusOut(BaseModel):
    status: ReorgPlanStatus


def _plan_out(p: PlanView) -> PlanOut:
    return PlanOut(
        id=p.id, status=p.status, created_by=p.created_by, created_at=p.created_at,
        items=[PlanItemOut(**vars(i)) for i in p.items],
    )  # fmt: skip


def _out(h: DocHit) -> DocumentOut:
    created: datetime = h.created_at
    return DocumentOut(
        id=h.document_id, attachment_id=h.attachment_id, title=strip_risky(h.title), doc_type=h.doc_type,
        status=h.status, document_date=h.document_date, summary=strip_risky(h.summary) if h.summary else None,
        snippet=strip_risky(h.snippet) if h.snippet else None, rank=h.rank, drive_url=h.drive_url,
        suspicious=h.suspicious, created_at=created, is_reference=h.is_reference,
    )  # fmt: skip


def _detail(d: DocDetail) -> DocumentDetailOut:
    return DocumentDetailOut(
        **_out(d.hit).model_dump(), file_name=d.file_name, facts=d.facts, unresolved=d.unresolved,
        links=[LinkOut(kind=x.kind, ref_id=x.ref_id, label=x.label, method=x.method) for x in d.links],
        chunk_count=d.chunk_count,
    )  # fmt: skip


@router.get("/documents")
def search(
    who: Owner,
    engine: Engine_,
    embedder: Embedder_,
    q: Annotated[str | None, Query(max_length=200)] = None,
    match: Literal["all", "any"] = "all",
    mode: Literal["words", "hybrid"] = "hybrid",
    type: Annotated[str | None, Query(max_length=32)] = None,
    status: DocumentStatus | None = None,
    person_id: UUID | None = None,
    unit_id: UUID | None = None,
    lease_id: UUID | None = None,
    case_id: UUID | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    needs_link: bool = False,
    reference_only: bool = False,
    limit: Annotated[int, Query(ge=1, le=50)] = 20,
) -> list[DocumentOut]:
    flt = DocFilter(
        type, status, person_id, unit_id, lease_id, case_id, date_from, date_to, needs_link,
        reference_only=reference_only,
    )  # fmt: skip
    with Session(engine) as session:
        if q and q.strip() and mode == "hybrid":
            hits = search_hybrid(session, who.company_id, q.strip(), flt, embedder, limit)
            return [_out(h) for h in hits]
        if q and q.strip():
            return [_out(h) for h in search_documents(session, who.company_id, q.strip(), flt, limit, match)]
        return [_out(h) for h in list_documents(session, who.company_id, flt, limit)]


@router.post("/documents/backfill", status_code=202, dependencies=[Depends(require_csrf), Depends(decision_limit)])
def backfill(who: Owner, client: WorkflowClient_) -> None:
    """Read, index and link documents filed before content reading existed, then propose a reorganisation plan."""
    enqueue.enqueue_backfill(client, who.company_id, datetime.now(UTC))


@router.get("/documents/reorg")
def current_plan(who: Owner, engine: Engine_) -> PlanOut | None:
    """The newest Drive reorganisation plan with its items and status, or null when there never was one."""
    with Session(engine) as session:
        plan = latest_plan(session, who.company_id)
    return _plan_out(plan) if plan else None


@router.post("/documents/reorg", dependencies=[Depends(require_csrf), Depends(decision_limit)])
def propose_plan(who: Owner, engine: Engine_) -> PlanCreatedOut:
    """Compare where filed documents sit with where layout v2 puts them and record the differences as a plan."""
    return PlanCreatedOut(plan_id=build_plan(engine, who.company_id, "owner"))


@router.post(
    "/documents/reorg/{plan_id}/decide", status_code=202, dependencies=[Depends(require_csrf), Depends(decision_limit)]
)
def decide(plan_id: UUID, body: PlanDecisionIn, who: Owner, engine: Engine_, client: WorkflowClient_) -> PlanStatusOut:
    """Approve all or some items, or reject. An approved plan is applied in the background; a repeat changes nothing."""
    try:
        status = decide_plan(
            engine, who.company_id, plan_id, body.approve, set(body.item_ids) if body.item_ids else None
        )
    except NotFoundError:
        raise HTTPException(status_code=404, detail=NOT_FOUND) from None
    if status is ReorgPlanStatus.approved:
        enqueue.enqueue_reorg(client, who.company_id, plan_id)
    return PlanStatusOut(status=status)


@router.get("/documents/{document_id}")
def read(document_id: UUID, who: Owner, engine: Engine_) -> DocumentDetailOut:
    try:
        with Session(engine) as session:
            return _detail(get_document(session, who.company_id, document_id))
    except NotFoundError:
        raise HTTPException(status_code=404, detail=NOT_FOUND) from None


def _write(engine: Engine, who: Principal, document_id: UUID, body: LinkIn, method: str) -> None:
    try:
        set_link(engine, who.company_id, document_id, body.kind, body.ref_id, method)
    except NotFoundError:
        raise HTTPException(status_code=404, detail=NOT_FOUND) from None
    build_plan(engine, who.company_id, "system", [document_id])  # a changed link may move the file: propose, never move


@router.post(
    "/documents/{document_id}/links", status_code=204, dependencies=[Depends(require_csrf), Depends(decision_limit)]
)
def add_link(document_id: UUID, body: LinkIn, who: Owner, engine: Engine_) -> None:
    _write(engine, who, document_id, body, "owner")


@router.delete(
    "/documents/{document_id}/links/{kind}/{ref_id}", status_code=204,
    dependencies=[Depends(require_csrf), Depends(decision_limit)],
)  # fmt: skip
def remove_link(document_id: UUID, kind: DocLinkKind, ref_id: UUID, who: Owner, engine: Engine_) -> None:
    _write(engine, who, document_id, LinkIn(kind=kind, ref_id=ref_id), "removed")


class ReferenceIn(BaseModel):
    is_reference: bool


class ReferenceOut(BaseModel):
    id: UUID
    is_reference: bool


@router.post(
    "/documents/{document_id}/reference",
    dependencies=[Depends(require_csrf), Depends(decision_limit), Depends(require_admin)],
)
def set_reference_flag(document_id: UUID, body: ReferenceIn, who: Owner, engine: Engine_) -> ReferenceOut:
    """Admin toggle: add or remove a document from the company reference library (ROZ clauses, standard terms). Every
    draft reads the library, so a member with only the inbox or maintenance section may not change it, and a
    person's own document is refused (409)."""
    try:
        flag = set_reference(engine, who.company_id, document_id, body.is_reference)
    except NotFoundError:
        raise HTTPException(status_code=404, detail=NOT_FOUND) from None
    except PersonalDocumentError:
        raise HTTPException(status_code=409, detail=PERSONAL_DOCUMENT) from None
    return ReferenceOut(id=document_id, is_reference=flag)
