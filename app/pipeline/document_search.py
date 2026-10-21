"""#9 Finding documents (M10): full-text over chunks plus structured filters, and the detail read model.

Read-only and company-scoped (invariant 4). Words go through `websearch_to_tsquery` (a bound parameter, never SQL
text) in Dutch and in `simple` form, matching the generated `document_chunks.tsv`. Metadata (title, summary, file
name) is searched too, so a document is found by what it is called as well as by what it says. Snippets are cut from
extracted document text: untrusted, so callers show them as data and never feed them to a model as instructions.
"""

import re
from dataclasses import dataclass, field
from datetime import date
from typing import Any, Literal
from uuid import UUID

from sqlalchemy import ColumnElement, and_, exists, func, or_, select
from sqlalchemy.dialects.postgresql import distinct_on
from sqlalchemy.orm import Session

from app.core.errors import NotFoundError
from app.db.enums import DocLinkKind, DocumentStatus
from app.db.models import (
    Case,
    DocumentChunk,
    DocumentLink,
    DocumentRow,
    Lease,
    Person,
    Unit,
)
from app.llm.agents.doc_qa import Passage

MAX_HITS = 50
SNIPPET_OPTIONS = "StartSel=«, StopSel=», MaxFragments=1, MaxWords=35, MinWords=12"
SEARCHABLE = (DocumentStatus.filed, DocumentStatus.review, DocumentStatus.pending)
DRIVE_URL = "https://drive.google.com/file/d/{}/view"


@dataclass(frozen=True)
class DocFilter:
    doc_type: str | None = None
    status: DocumentStatus | None = None
    person_id: UUID | None = None
    unit_id: UUID | None = None
    lease_id: UUID | None = None
    case_id: UUID | None = None
    date_from: date | None = None
    date_to: date | None = None
    needs_link: bool = False
    any_link: tuple[tuple[DocLinkKind, UUID], ...] = ()  # linked to at least one of these (a case's whole scope)
    readable_only: bool = False  # drops documents flagged suspicious: for text that reaches a model


@dataclass(frozen=True)
class DocHit:
    document_id: UUID
    attachment_id: UUID
    title: str
    doc_type: str
    status: DocumentStatus
    document_date: date | None
    summary: str | None
    snippet: str | None
    rank: float
    drive_url: str | None
    suspicious: bool
    created_at: Any


@dataclass(frozen=True)
class LinkedRef:
    kind: DocLinkKind
    ref_id: UUID
    label: str
    method: str


@dataclass(frozen=True)
class DocDetail:
    hit: DocHit
    file_name: str
    facts: dict[str, Any] | None
    unresolved: list[str]
    links: list[LinkedRef] = field(default_factory=list)
    chunk_count: int = 0


def _link_exists(company_id: UUID, kind: DocLinkKind, ref_id: UUID) -> ColumnElement[bool]:
    return exists().where(
        DocumentLink.document_id == DocumentRow.id,
        DocumentLink.company_id == company_id,
        DocumentLink.kind == kind,
        DocumentLink.ref_id == ref_id,
        DocumentLink.method != "removed",
    )


def _filters(company_id: UUID, flt: DocFilter) -> list[ColumnElement[bool]]:
    conds: list[ColumnElement[bool]] = [DocumentRow.company_id == company_id]
    conds.append(DocumentRow.status == flt.status if flt.status else DocumentRow.status.in_(SEARCHABLE))
    if flt.doc_type:
        conds.append(DocumentRow.doc_type == flt.doc_type)
    for kind, ref in ((DocLinkKind.person, flt.person_id), (DocLinkKind.unit, flt.unit_id),
                      (DocLinkKind.lease, flt.lease_id), (DocLinkKind.case, flt.case_id)):  # fmt: skip
        if ref is not None:
            conds.append(_link_exists(company_id, kind, ref))
    if flt.date_from:
        conds.append(func.coalesce(DocumentRow.document_date, func.date(DocumentRow.created_at)) >= flt.date_from)
    if flt.date_to:
        conds.append(func.coalesce(DocumentRow.document_date, func.date(DocumentRow.created_at)) <= flt.date_to)
    if flt.any_link:
        conds.append(or_(*(_link_exists(company_id, kind, ref) for kind, ref in flt.any_link)))
    if flt.readable_only:
        conds.append(DocumentRow.suspicious.is_(False))
    if flt.needs_link:
        unresolved = func.coalesce(func.jsonb_array_length(DocumentRow.facts["unresolved"]), 0)
        conds.append(and_(DocumentRow.facts.is_not(None), unresolved > 0))
    return conds


def _hit(row: Any, snippet: str | None, rank: float) -> DocHit:
    d: DocumentRow = row
    return DocHit(
        document_id=d.id, attachment_id=d.attachment_id, title=d.title, doc_type=d.doc_type, status=d.status,
        document_date=d.document_date, summary=d.summary, snippet=snippet, rank=rank,
        drive_url=DRIVE_URL.format(d.drive_file_id) if d.drive_file_id else None, suspicious=d.suspicious,
        created_at=d.created_at,
    )  # fmt: skip


_WORD = re.compile(r"[^\W_]{3,}")
_FILLER = (  # the `simple` index half keeps stop words, so a question's filler must not become a search term
    "the and for what does say about with this that are from his her its has have was were can you your please "
    "een het van voor met wat staat hoe zegt over deze die dat zijn heeft hebben wordt kan mijn jouw"
)
_STOP = frozenset(_FILLER.split())


def any_of(query: str) -> str:
    """ "what does the lease say about the deposit" -> "lease or deposit": any word may match, best overlap first."""
    words = [w.lower() for w in _WORD.findall(query) if w.lower() not in _STOP]
    return " or ".join(dict.fromkeys(words)) or query


def _tsquery(query: str) -> Any:
    return func.websearch_to_tsquery("dutch", query).op("||")(func.websearch_to_tsquery("simple", query))


def _best_chunks(company_id: UUID, tsq: Any) -> Any:
    """One row per document: its best matching chunk and that chunk's rank."""
    rank = func.ts_rank_cd(DocumentChunk.tsv, tsq).label("rank")
    return (
        select(DocumentChunk.document_id, DocumentChunk.text, rank)
        .where(DocumentChunk.company_id == company_id, DocumentChunk.tsv.op("@@")(tsq))
        .ext(distinct_on(DocumentChunk.document_id))
        .order_by(DocumentChunk.document_id, rank.desc())
        .subquery()
    )


def _content_hits(session: Session, company_id: UUID, query: str, flt: DocFilter, limit: int) -> list[DocHit]:
    """Best chunk per document, ranked by `ts_rank_cd`, with a highlighted snippet from that chunk."""
    best = _best_chunks(company_id, _tsquery(query))
    snippet = func.ts_headline("dutch", best.c.text, func.websearch_to_tsquery("dutch", query), SNIPPET_OPTIONS)
    stmt = (
        select(DocumentRow, snippet, best.c.rank)
        .join(best, best.c.document_id == DocumentRow.id)
        .where(*_filters(company_id, flt))
        .order_by(best.c.rank.desc(), DocumentRow.created_at.desc())
        .limit(limit)
    )
    return [_hit(d, snip, float(r)) for d, snip, r in session.execute(stmt)]


def top_passages(session: Session, company_id: UUID, question: str, flt: DocFilter = DocFilter(),  # noqa: B008
                 limit: int = 4) -> list[Passage]:  # fmt: skip
    """Best chunk of the best `limit` documents for a question (any word may match; most overlap ranks first)."""
    best = _best_chunks(company_id, _tsquery(any_of(question)))
    stmt = (
        select(DocumentRow, best.c.text, best.c.rank)
        .join(best, best.c.document_id == DocumentRow.id)
        .where(*_filters(company_id, flt))
        .order_by(best.c.rank.desc(), DocumentRow.created_at.desc())
        .limit(max(1, min(limit, MAX_HITS)))
    )
    return [Passage(d.id, d.title, d.doc_type, d.document_date, text, float(r)) for d, text, r in session.execute(stmt)]


def _metadata_hits(session: Session, company_id: UUID, query: str, flt: DocFilter, skip: set[UUID],
                   limit: int) -> list[DocHit]:  # fmt: skip
    pattern = or_(*(col.icontains(query, autoescape=True) for col in (DocumentRow.title, DocumentRow.summary,
                                                                       DocumentRow.file_name)))  # fmt: skip
    stmt = select(DocumentRow).where(*_filters(company_id, flt), pattern).order_by(DocumentRow.created_at.desc())
    return [_hit(d, None, 0.0) for d in session.scalars(stmt.limit(limit + len(skip))) if d.id not in skip][:limit]


def search_documents(session: Session, company_id: UUID, query: str, flt: DocFilter = DocFilter(),  # noqa: B008
                     limit: int = 20, match: Literal["all", "any"] = "all") -> list[DocHit]:  # fmt: skip
    """Content matches first (by rank), then documents whose title, summary or file name contains the query.
    `match="all"` needs every word (typed search); `"any"` takes any word, ranked by overlap (a question)."""
    cap = max(1, min(limit, MAX_HITS))
    hits = _content_hits(session, company_id, any_of(query) if match == "any" else query, flt, cap)
    if len(hits) < cap:
        hits += _metadata_hits(session, company_id, query, flt, {h.document_id for h in hits}, cap - len(hits))
    return hits


def list_documents(session: Session, company_id: UUID, flt: DocFilter = DocFilter(),  # noqa: B008
                   limit: int = 20) -> list[DocHit]:  # fmt: skip
    stmt = select(DocumentRow).where(*_filters(company_id, flt)).order_by(DocumentRow.created_at.desc(), DocumentRow.id)
    return [_hit(d, None, 0.0) for d in session.scalars(stmt.limit(max(1, min(limit, MAX_HITS))))]


def _labels(session: Session, company_id: UUID, links: list[DocumentLink]) -> dict[tuple[DocLinkKind, UUID], str]:
    out: dict[tuple[DocLinkKind, UUID], str] = {}
    people = [x.ref_id for x in links if x.kind is DocLinkKind.person]
    units = [x.ref_id for x in links if x.kind is DocLinkKind.unit]
    cases = [x.ref_id for x in links if x.kind is DocLinkKind.case]
    leases = [x.ref_id for x in links if x.kind is DocLinkKind.lease]
    for pid, name in session.execute(select(Person.id, Person.display_name).where(
            Person.company_id == company_id, Person.id.in_(people))):  # fmt: skip
        out[(DocLinkKind.person, pid)] = name
    for uid, label in session.execute(select(Unit.id, Unit.label).where(
            Unit.company_id == company_id, Unit.id.in_(units))):  # fmt: skip
        out[(DocLinkKind.unit, uid)] = label
    for cid, cat, summary in session.execute(select(Case.id, Case.category, Case.summary).where(
            Case.company_id == company_id, Case.id.in_(cases))):  # fmt: skip
        out[(DocLinkKind.case, cid)] = f"{cat.value}: {' '.join(summary.split())[:60]}".strip(": ")
    for lid, label, start in session.execute(select(Lease.id, Unit.label, Lease.valid_from).join(
            Unit, Unit.id == Lease.unit_id).where(Lease.company_id == company_id, Lease.id.in_(leases))):  # fmt: skip
        out[(DocLinkKind.lease, lid)] = f"{label} (from {start.isoformat()})"
    return out


def get_document(session: Session, company_id: UUID, document_id: UUID) -> DocDetail:
    doc = session.scalar(select(DocumentRow).where(DocumentRow.id == document_id, DocumentRow.company_id == company_id))
    if doc is None:
        raise NotFoundError(f"document {document_id} not found")
    links = list(session.scalars(select(DocumentLink).where(
        DocumentLink.document_id == document_id, DocumentLink.company_id == company_id,
        DocumentLink.method != "removed").order_by(DocumentLink.kind, DocumentLink.score.desc())))  # fmt: skip
    names = _labels(session, company_id, links)
    refs = [
        LinkedRef(x.kind, x.ref_id, names[(x.kind, x.ref_id)], x.method) for x in links if (x.kind, x.ref_id) in names
    ]
    count = session.scalar(select(func.count()).select_from(DocumentChunk).where(
        DocumentChunk.document_id == document_id, DocumentChunk.company_id == company_id))  # fmt: skip
    facts = {k: v for k, v in (doc.facts or {}).items() if k != "unresolved"} if doc.facts else None
    unresolved = list((doc.facts or {}).get("unresolved", []))
    return DocDetail(_hit(doc, None, 0.0), doc.file_name, facts, unresolved, refs, int(count or 0))
