"""#9 Document linking (M10): tie a document to the real person, unit, lease and case it is about.

Evidence, strongest first: the message the file came with (its case, and through it the unit, lease and primary
person; its sender), then names and addresses the reader found in the text matched against the directory. A name or
address that matches several rows equally is ambiguous and links nothing: a wrong link would put a lease in front of
the wrong tenant, so Harjot resolves those (`unresolved`). Owner links (`method="owner"`) are never overwritten.
"""

import re
import unicodedata
from dataclasses import dataclass, field
from datetime import date
from typing import Any
from uuid import UUID

from rapidfuzz import fuzz
from sqlalchemy import Engine, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.core.errors import NotFoundError
from app.db.enums import DocLinkKind
from app.db.models import (
    AttachmentRow,
    Case,
    CaseLink,
    DocumentLink,
    DocumentRow,
    Lease,
    LeaseParty,
    MessageRow,
    Person,
    Unit,
)

NAME_MIN = 88.0
UNIT_MIN = 90.0
TIE = 2.0  # best matches closer than this are ambiguous
_NOISE = re.compile(r"\b(dhr|mevr|mr|mw|de heer|mevrouw|mr\.|drs|ir)\b|[^a-z0-9 ]")


@dataclass(frozen=True)
class Link:
    kind: DocLinkKind
    ref_id: UUID
    method: str
    score: float


@dataclass(frozen=True)
class Match:
    ref_id: UUID | None
    score: float
    ambiguous: bool


@dataclass
class LinkOutcome:
    links: list[Link] = field(default_factory=list)
    unresolved: list[str] = field(default_factory=list)  # what the document names that could not be linked


def fold(text: str) -> str:
    ascii_text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode().lower()
    return " ".join(_NOISE.sub(" ", ascii_text).split())


def _best(scored: list[tuple[UUID, float]], minimum: float) -> Match:
    ranked = sorted((s for s in scored if s[1] >= minimum), key=lambda s: s[1], reverse=True)
    if not ranked:
        return Match(None, 0.0, False)
    if len(ranked) > 1 and ranked[0][1] - ranked[1][1] < TIE:
        return Match(None, ranked[0][1], True)
    return Match(ranked[0][0], ranked[0][1], False)


def match_name(name: str, people: list[tuple[UUID, str]]) -> Match:
    """Fuzzy person match. A single-word name only matches an identical single word (no "Jan" for every Jan)."""
    wanted = fold(name)
    if not wanted:
        return Match(None, 0.0, False)
    scored: list[tuple[UUID, float]] = []
    for person_id, display in people:
        have = fold(display)
        score = fuzz.token_sort_ratio(wanted, have)
        if len(wanted.split()) < 2 or len(have.split()) < 2:
            score = 100.0 if wanted == have else 0.0
        scored.append((person_id, score))
    return _best(scored, NAME_MIN)


def match_unit(hint: str, units: list[tuple[UUID, str, str | None]]) -> Match:
    """Fuzzy unit match on label and address; a hint that fits several units ("Kerkstraat 12") is ambiguous."""
    wanted = fold(hint)
    if not wanted:
        return Match(None, 0.0, False)
    scored = [
        (unit_id, max(fuzz.token_set_ratio(wanted, fold(text)) for text in (label, address) if text))
        for unit_id, label, address in units
        if label or address
    ]
    return _best(scored, UNIT_MIN)


def active_lease(leases: list[tuple[UUID, date, date | None]], day: date) -> UUID | None:
    """The one lease valid on `day`, else None (none, or an overlap nobody should guess about)."""
    current = [lid for lid, start, end in leases if start <= day and (end is None or end >= day)]
    return current[0] if len(current) == 1 else None


def _message_links(session: Session, company_id: UUID, message: MessageRow) -> list[Link]:
    links: list[Link] = []
    if message.person_id:
        links.append(Link(DocLinkKind.person, message.person_id, "message", 1.0))
    case = session.execute(
        select(Case).join(CaseLink, CaseLink.case_id == Case.id).where(
            CaseLink.message_id == message.id, CaseLink.company_id == company_id, Case.company_id == company_id
        )
    ).scalar_one_or_none()  # fmt: skip
    if case is not None:
        links.append(Link(DocLinkKind.case, case.id, "message", 1.0))
        for kind, ref in ((DocLinkKind.unit, case.unit_id), (DocLinkKind.lease, case.lease_id),
                          (DocLinkKind.person, case.primary_person_id)):  # fmt: skip
            if ref is not None:
                links.append(Link(kind, ref, "case", 1.0))
    return links


def _content_links(
    session: Session, company_id: UUID, facts: dict[str, Any] | None, doc_day: date, out: LinkOutcome
) -> None:
    facts = facts or {}
    people = [(p.id, p.display_name) for p in session.scalars(
        select(Person).where(Person.company_id == company_id, Person.valid_to.is_(None)))]  # fmt: skip
    for party in facts.get("parties", []):
        if party["role"] == "landlord":
            continue
        found = match_name(party["name"], people)
        if found.ref_id is not None:
            out.links.append(Link(DocLinkKind.person, found.ref_id, "fuzzy", found.score / 100))
        else:
            out.unresolved.append(f"person: {party['name']}")
    hint = facts.get("unit_hint")
    if not hint:
        return
    units = [(u.id, u.label, u.address) for u in session.scalars(
        select(Unit).where(Unit.company_id == company_id, Unit.valid_to.is_(None)))]  # fmt: skip
    found = match_unit(hint, units)
    if found.ref_id is None:
        out.unresolved.append(f"unit: {hint}")
        return
    out.links.append(Link(DocLinkKind.unit, found.ref_id, "fuzzy", found.score / 100))
    leases = [(le.id, le.valid_from, le.valid_to) for le in session.scalars(
        select(Lease).where(Lease.company_id == company_id, Lease.unit_id == found.ref_id))]  # fmt: skip
    lease_id = active_lease(leases, doc_day)
    if lease_id is not None:
        out.links.append(Link(DocLinkKind.lease, lease_id, "fuzzy", found.score / 100))


def _tenant_unit_links(session: Session, company_id: UUID, out: LinkOutcome, day: date) -> None:
    """A tenant named in the document with exactly one current lease also places the document in that unit."""
    have_unit = any(link.kind is DocLinkKind.unit for link in out.links)
    people = {link.ref_id for link in out.links if link.kind is DocLinkKind.person and link.method == "fuzzy"}
    if have_unit or len(people) != 1:
        return
    rows = session.execute(
        select(Lease.id, Lease.unit_id, Lease.valid_from, Lease.valid_to)
        .join(LeaseParty, LeaseParty.lease_id == Lease.id)
        .where(Lease.company_id == company_id, LeaseParty.company_id == company_id, LeaseParty.person_id.in_(people))
    ).all()  # fmt: skip
    lease_id = active_lease([(r[0], r[2], r[3]) for r in rows], day)
    if lease_id is not None:
        unit_id = next(r[1] for r in rows if r[0] == lease_id)
        out.links.append(Link(DocLinkKind.unit, unit_id, "lease", 0.9))
        out.links.append(Link(DocLinkKind.lease, lease_id, "lease", 0.9))


def _dedupe(links: list[Link]) -> list[Link]:
    best: dict[tuple[DocLinkKind, UUID], Link] = {}
    for link in links:
        key = (link.kind, link.ref_id)
        if key not in best or link.score > best[key].score:
            best[key] = link
    return list(best.values())


def resolve_links(
    session: Session, company_id: UUID, message: MessageRow, facts: dict[str, Any] | None, document_date: date | None
) -> LinkOutcome:
    """Every link the evidence supports (nothing is stored): message and case first, then the reader's names."""
    day = document_date or message.sent_at.date()
    out = LinkOutcome(links=_message_links(session, company_id, message))
    _content_links(session, company_id, facts, day, out)
    _tenant_unit_links(session, company_id, out, day)
    out.links = _dedupe(out.links)
    return out


def link_document(engine: Engine, company_id: UUID, attachment_id: UUID) -> LinkOutcome:
    """Compute and store the links of one document. Idempotent; never touches a link the owner set."""
    with Session(engine) as session, session.begin():
        found = session.execute(
            select(DocumentRow, MessageRow)
            .join(AttachmentRow, AttachmentRow.id == DocumentRow.attachment_id)
            .join(MessageRow, MessageRow.id == AttachmentRow.message_id)
            .where(
                DocumentRow.attachment_id == attachment_id,
                DocumentRow.company_id == company_id,
                MessageRow.company_id == company_id,
            )
        ).one_or_none()
        if found is None:
            raise NotFoundError(f"no document for attachment {attachment_id} in company {company_id}")
        doc, message = found
        out = resolve_links(session, company_id, message, doc.facts, doc.document_date)
        if doc.facts is not None:  # what the reader named but the directory could not place: Harjot resolves it
            doc.facts = {**doc.facts, "unresolved": out.unresolved}
        rows = [
            {"company_id": company_id, "document_id": doc.id, "kind": link.kind, "ref_id": link.ref_id,
             "method": link.method, "score": link.score}
            for link in out.links
        ]  # fmt: skip
        if rows:
            session.execute(
                insert(DocumentLink)
                .values(rows)
                .on_conflict_do_nothing(index_elements=["document_id", "kind", "ref_id"])
            )
    return out


_DIRECTORY: dict[DocLinkKind, type[Person] | type[Unit] | type[Lease] | type[Case]] = {
    DocLinkKind.person: Person,
    DocLinkKind.unit: Unit,
    DocLinkKind.lease: Lease,
    DocLinkKind.case: Case,
}


def set_link(engine: Engine, company_id: UUID, document_id: UUID, kind: DocLinkKind, ref_id: UUID, method: str) -> None:
    """Owner action: `method="owner"` adds or confirms a link, `"removed"` hides one and keeps automation from
    re-adding it. The document and the target must both belong to the company."""
    model = _DIRECTORY[kind]
    with Session(engine) as session, session.begin():
        doc = session.scalar(
            select(DocumentRow.id).where(DocumentRow.id == document_id, DocumentRow.company_id == company_id)
        )
        target = session.scalar(select(model.id).where(model.id == ref_id, model.company_id == company_id))
        if doc is None or target is None:
            raise NotFoundError("document or link target not found")
        stmt = insert(DocumentLink).values(
            company_id=company_id, document_id=document_id, kind=kind, ref_id=ref_id, method=method, score=1.0
        )
        session.execute(
            stmt.on_conflict_do_update(
                index_elements=["document_id", "kind", "ref_id"], set_={"method": method, "score": 1.0}
            )
        )
        # the chunk headers and the document vector name the unit and people: let the reindex step rebuild them
        session.execute(
            update(DocumentRow).where(DocumentRow.id == document_id, DocumentRow.company_id == company_id)
            .values(index_version=None)
        )  # fmt: skip


def set_reference(engine: Engine, company_id: UUID, document_id: UUID, is_reference: bool) -> bool:
    """Owner action: mark or unmark a company document as part of the reference library."""
    with Session(engine) as session, session.begin():
        doc_id = session.scalar(
            select(DocumentRow.id).where(DocumentRow.id == document_id, DocumentRow.company_id == company_id)
        )
        if doc_id is None:
            raise NotFoundError("document not found")
        session.execute(
            update(DocumentRow)
            .where(DocumentRow.id == document_id, DocumentRow.company_id == company_id)
            .values(is_reference=is_reference, index_version=None)
        )
    return is_reference
