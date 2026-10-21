"""Document library: search and filter, one document with its facts and links, and the owner's link fixes.

Read routes are company-scoped through the session principal. Snippets and summaries come from document text and are
returned as data. Writes (link, unlink) need the CSRF header; foreign ids answer the same 404 as missing ones.
"""

from datetime import date, datetime
from typing import Annotated, Any, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import AwareDatetime, BaseModel
from sqlalchemy import Engine
from sqlalchemy.orm import Session

from app.api.deps import get_engine
from app.api.v1.auth import Principal, require_csrf, require_principal
from app.api.v1.ratelimit import decision_limit
from app.core.errors import NotFoundError
from app.db.enums import DocLinkKind, DocumentStatus
from app.pipeline.document_links import set_link
from app.pipeline.document_search import DocDetail, DocFilter, DocHit, get_document, list_documents, search_documents

router = APIRouter(tags=["documents"])
NOT_FOUND = "not found"
Owner = Annotated[Principal, Depends(require_principal)]
Engine_ = Annotated[Engine, Depends(get_engine)]


class DocumentOut(BaseModel):
    id: UUID
    attachment_id: UUID
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


def _out(h: DocHit) -> DocumentOut:
    created: datetime = h.created_at
    return DocumentOut(
        id=h.document_id, attachment_id=h.attachment_id, title=h.title, doc_type=h.doc_type, status=h.status,
        document_date=h.document_date, summary=h.summary, snippet=h.snippet, rank=h.rank, drive_url=h.drive_url,
        suspicious=h.suspicious, created_at=created,
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
    q: Annotated[str | None, Query(max_length=200)] = None,
    match: Literal["all", "any"] = "all",
    type: Annotated[str | None, Query(max_length=32)] = None,
    status: DocumentStatus | None = None,
    person_id: UUID | None = None,
    unit_id: UUID | None = None,
    lease_id: UUID | None = None,
    case_id: UUID | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    needs_link: bool = False,
    limit: Annotated[int, Query(ge=1, le=50)] = 20,
) -> list[DocumentOut]:
    flt = DocFilter(type, status, person_id, unit_id, lease_id, case_id, date_from, date_to, needs_link)
    with Session(engine) as session:
        if q and q.strip():
            return [_out(h) for h in search_documents(session, who.company_id, q.strip(), flt, limit, match)]
        return [_out(h) for h in list_documents(session, who.company_id, flt, limit)]


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
