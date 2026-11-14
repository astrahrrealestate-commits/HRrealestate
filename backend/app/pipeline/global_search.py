"""Global search behind the dashboard's ⌘K palette: people, units, cases and documents in one bounded call.

Substring match (ILIKE) on short text columns, always filtered by `company_id` (invariant 4). Deliberately not
semantic: document meaning search lives in `document_search`. Hit titles come from tenant-derived text, so callers
return them as data.
"""

import unicodedata
from dataclasses import dataclass
from enum import StrEnum
from uuid import UUID

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.db.enums import PersonKind
from app.db.models import Case, DocumentRow, Person, Unit

MIN_QUERY_CHARS = 2
MAX_QUERY_CHARS = 100
PER_KIND_LIMIT = 5
SUMMARY_PREVIEW_CHARS = 90


class HitKind(StrEnum):
    person = "person"
    unit = "unit"
    case = "case"
    document = "document"


@dataclass(frozen=True)
class SearchHit:
    kind: HitKind
    id: UUID
    title: str
    subtitle: str | None
    person_kind: PersonKind | None = None  # set for people, so the SPA routes on the kind, not on display text


def clean_query(raw: str) -> str | None:
    """Collapse whitespace, drop control characters (Postgres rejects NUL) and cap the length; None when too short."""
    spaced = " ".join(raw[: 4 * MAX_QUERY_CHARS].split())
    text = "".join(ch for ch in spaced if unicodedata.category(ch) != "Cc")[:MAX_QUERY_CHARS].strip()
    return text if len(text) >= MIN_QUERY_CHARS else None


def like_pattern(text: str) -> str:
    """Contains-pattern for ILIKE with `%`, `_` and the escape character taken literally."""
    escaped = text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


def _people(session: Session, company_id: UUID, pattern: str, limit: int) -> list[SearchHit]:
    rows = session.execute(
        select(Person.id, Person.display_name, Person.kind, Person.trade)
        .where(
            Person.company_id == company_id,
            Person.valid_to.is_(None),
            or_(Person.display_name.ilike(pattern, escape="\\"), Person.trade.ilike(pattern, escape="\\")),
        )
        .order_by(Person.display_name)
        .limit(limit)
    ).all()
    return [SearchHit(HitKind.person, r.id, r.display_name, r.trade or r.kind.value, r.kind) for r in rows]


def _units(session: Session, company_id: UUID, pattern: str, limit: int) -> list[SearchHit]:
    rows = session.execute(
        select(Unit.id, Unit.label, Unit.address)
        .where(
            Unit.company_id == company_id,
            Unit.valid_to.is_(None),
            or_(Unit.label.ilike(pattern, escape="\\"), Unit.address.ilike(pattern, escape="\\")),
        )
        .order_by(Unit.label)
        .limit(limit)
    ).all()
    return [SearchHit(HitKind.unit, r.id, r.label, r.address) for r in rows]


def _cases(session: Session, company_id: UUID, pattern: str, limit: int) -> list[SearchHit]:
    rows = session.execute(
        select(Case.id, Case.category, Case.state, Case.summary)
        .where(Case.company_id == company_id, Case.summary.ilike(pattern, escape="\\"))
        .order_by(Case.opened_at.desc())
        .limit(limit)
    ).all()
    return [
        SearchHit(HitKind.case, r.id, " ".join(r.summary.split())[:SUMMARY_PREVIEW_CHARS], f"{r.category} · {r.state}")
        for r in rows
    ]


def _documents(session: Session, company_id: UUID, pattern: str, limit: int) -> list[SearchHit]:
    rows = session.execute(
        select(DocumentRow.id, DocumentRow.title, DocumentRow.doc_type)
        .where(
            DocumentRow.company_id == company_id,
            or_(DocumentRow.title.ilike(pattern, escape="\\"), DocumentRow.file_name.ilike(pattern, escape="\\")),
        )
        .order_by(DocumentRow.created_at.desc())
        .limit(limit)
    ).all()
    return [SearchHit(HitKind.document, r.id, r.title, r.doc_type) for r in rows]


def global_search(
    session: Session, company_id: UUID, raw_query: str, *, limit: int = PER_KIND_LIMIT
) -> list[SearchHit]:
    """Up to `limit` hits per kind, grouped people, units, cases, documents. Empty for a too-short query."""
    query = clean_query(raw_query)
    if query is None:
        return []
    pattern = like_pattern(query)
    return [
        *_people(session, company_id, pattern, limit),
        *_units(session, company_id, pattern, limit),
        *_cases(session, company_id, pattern, limit),
        *_documents(session, company_id, pattern, limit),
    ]
