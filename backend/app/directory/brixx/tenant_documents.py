"""The BRIXX documents of one tenant: their own, their contracts', their unit's and their building's.

BRIXX stores a file once (`PRG_DOCUMENT`) and links it to what it belongs to: a relatie (`PRG_RELATIEDOCUMENT`, typed
by `TYP_RELATIEDOCUMENT`) or any entity through `PRG_DOCUMENT_LINK` (`SYS_ENTITEITTYPE`: 9 contract, 10 relatie, 11
object = building, 12 subobject = unit). A tenant's documents are those linked to their relatie, to the contracts of
their leases, to their units and to those units' buildings. The file bytes are in object storage once the download
pipeline stored them (`brixx_documents`); until then the document is listed as not yet available. Reads the mirror
for one company with indexed filters, never the whole table. Soft-deleted mirror rows are not listed.
"""

from dataclasses import dataclass
from datetime import date
from typing import Any
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.orm import Session

from app.db.brixx_erasure import mirror_table
from app.db.enums import BrixxDocumentStatus, PersonKind
from app.db.models import Lease, LeaseParty, Person, Unit
from app.db.models.brixx import BrixxDocument

RELATIE_DOCUMENT, DOCUMENT_LINK, DOCUMENT = "prg_relatiedocument", "prg_document_link", "prg_document"
DOCUMENT_TYPE, DOCUMENT_CATEGORY, RELATIE_DOCUMENT_TYPE = "typ_document", "typ_documentcategorie", "typ_relatiedocument"
SUBOBJECT_TABLE = "prg_subobject"
LINK_CONTRACT, LINK_RELATIE, LINK_OBJECT, LINK_SUBOBJECT = 9, 10, 11, 12
# Where a document hangs, in the order a tenant cares: their own, their contract's, their unit's, their building's.
SOURCES = {LINK_RELATIE: "Tenant", LINK_CONTRACT: "Contract", LINK_SUBOBJECT: "Unit", LINK_OBJECT: "Building"}
_RANK = {label: rank for rank, label in enumerate(SOURCES.values())}


@dataclass(frozen=True)
class TenantDocument:
    document_id: int
    title: str
    file_name: str
    category: str
    source: str
    size_bytes: int | None
    added_on: date | None
    storage_key: str | None  # None until the file is downloaded

    @property
    def available(self) -> bool:
        return self.storage_key is not None


def _t(name: str, *columns: tuple[str, sa.types.TypeEngine[Any]]) -> sa.Table:
    return mirror_table(name, *(sa.Column(n, kind) for n, kind in columns), sa.Column("_deleted_at", sa.DateTime(True)))


_BIGINT, _TEXT, _SMALL = sa.BigInteger(), sa.Text(), sa.SmallInteger()


def _tenant_scope(session: Session, company_id: UUID, person: Person) -> tuple[int, list[int], list[int]]:
    """(relatie id, contract ids, subobject ids) of a tenant person."""
    rows = session.execute(
        sa.select(Lease.brixx_ref, Unit.brixx_ref)
        .join(LeaseParty, LeaseParty.lease_id == Lease.id)
        .join(Unit, Unit.id == Lease.unit_id)
        .where(
            Lease.company_id == company_id,
            LeaseParty.company_id == company_id,
            LeaseParty.person_id == person.id,
            Lease.brixx_ref.is_not(None),
        )
    ).all()
    contracts = sorted({int(ref.split(":", 1)[0]) for ref, _ in rows if ref and ref.split(":", 1)[0].isdigit()})
    units = sorted({int(unit) for _, unit in rows if unit and unit.isdigit()})
    return int(person.brixx_ref or 0), contracts, units


def _buildings(session: Session, company_id: UUID, subobjects: list[int]) -> list[int]:
    if not subobjects:
        return []
    sub = _t(SUBOBJECT_TABLE, ("prg_subobjectid", _BIGINT), ("prg_objectid", _BIGINT))
    found = session.scalars(
        sa.select(sub.c.prg_objectid).where(
            sub.c.company_id == company_id, sub.c.prg_subobjectid.in_(subobjects), sub.c._deleted_at.is_(None)
        )
    )
    return sorted({int(o) for o in found if o is not None})


def _linked(
    session: Session, company_id: UUID, relatie: int, contracts: list[int], subobjects: list[int]
) -> dict[int, tuple[str, str | None]]:
    """document id -> (source label, BRIXX's own relatie-document label), the closest source winning."""
    link = _t(DOCUMENT_LINK, ("prg_documentid", _BIGINT), ("entiteitid", _BIGINT), ("sys_entiteittypeid", _BIGINT))
    own = _t(
        RELATIE_DOCUMENT,
        ("prg_documentid", _BIGINT),
        ("prg_relatieid", _BIGINT),
        ("typ_relatiedocumentid", _BIGINT),
        ("indverwijderd", _SMALL),
    )
    kinds = _t(RELATIE_DOCUMENT_TYPE, ("typ_relatiedocumentid", _BIGINT), ("benaming", _TEXT))
    wanted = {
        LINK_RELATIE: [relatie],
        LINK_CONTRACT: contracts,
        LINK_SUBOBJECT: subobjects,
        LINK_OBJECT: _buildings(session, company_id, subobjects),
    }
    clauses = [
        sa.and_(link.c.sys_entiteittypeid == kind, link.c.entiteitid.in_(ids)) for kind, ids in wanted.items() if ids
    ]
    found: dict[int, tuple[str, str | None]] = {}

    def keep(document: int, source: str, label: str | None) -> None:
        if document not in found or _RANK[source] < _RANK[found[document][0]]:
            found[document] = (source, label)

    for document, kind in session.execute(
        sa.select(link.c.prg_documentid, link.c.sys_entiteittypeid).where(
            link.c.company_id == company_id, link.c._deleted_at.is_(None), sa.or_(*clauses)
        )
    ).all():
        keep(int(document), SOURCES[int(kind)], None)
    for document, label in session.execute(
        sa.select(own.c.prg_documentid, kinds.c.benaming)
        .outerjoin(
            kinds,
            sa.and_(
                kinds.c.company_id == own.c.company_id, kinds.c.typ_relatiedocumentid == own.c.typ_relatiedocumentid
            ),
        )
        .where(
            own.c.company_id == company_id,
            own.c._deleted_at.is_(None),
            sa.func.coalesce(own.c.indverwijderd, 0) == 0,
            own.c.prg_relatieid == relatie,
            own.c.prg_documentid.is_not(None),
        )
    ).all():
        keep(int(document), SOURCES[LINK_RELATIE], label)
    return found


def _stored(session: Session, company_id: UUID, ids: list[int]) -> dict[int, str]:
    """document id -> storage key of its newest stored file."""
    rows = session.execute(
        sa.select(BrixxDocument.document_id, BrixxDocument.storage_key)
        .where(
            BrixxDocument.company_id == company_id,
            BrixxDocument.document_id.in_(ids),
            BrixxDocument.status == BrixxDocumentStatus.stored,
            BrixxDocument.storage_key.is_not(None),
        )
        .order_by(BrixxDocument.updated_at)
    ).all()
    return {int(doc): str(key) for doc, key in rows}  # later (newer) rows overwrite earlier ones


def tenant_documents(session: Session, company_id: UUID, person_id: UUID) -> list[TenantDocument] | None:
    """The documents of a tenant of the company, newest first; None when there is no such tenant."""
    person = tenant_person(session, company_id, person_id)
    if person is None:
        return None
    if not person.brixx_ref or not person.brixx_ref.isdigit():
        return []  # a tenant that did not come from BRIXX has no BRIXX documents
    relatie, contracts, subobjects = _tenant_scope(session, company_id, person)
    linked = _linked(session, company_id, relatie, contracts, subobjects)
    if not linked:
        return []
    doc = _t(
        DOCUMENT,
        ("prg_documentid", _BIGINT),
        ("benaming", _TEXT),
        ("filenaam", _TEXT),
        ("groottebytes", _BIGINT),
        ("typ_documentcategorieid", _BIGINT),
        ("newdatetime", sa.DateTime(True)),
    )
    cat = _t(DOCUMENT_CATEGORY, ("typ_documentcategorieid", _BIGINT), ("benaming", _TEXT))
    rows = session.execute(
        sa.select(
            doc.c.prg_documentid, doc.c.benaming, doc.c.filenaam, doc.c.groottebytes, doc.c.newdatetime, cat.c.benaming
        )
        .outerjoin(
            cat,
            sa.and_(
                cat.c.company_id == doc.c.company_id, cat.c.typ_documentcategorieid == doc.c.typ_documentcategorieid
            ),
        )
        .where(doc.c.company_id == company_id, doc.c._deleted_at.is_(None), doc.c.prg_documentid.in_(list(linked)))
    ).all()
    stored = _stored(session, company_id, [int(r[0]) for r in rows])
    out = [
        TenantDocument(
            document_id=int(document),
            title=(title or name or f"Document {document}").strip(),
            file_name=(name or title or f"document-{document}").strip(),
            category=(linked[int(document)][1] or category or "Document").strip(),
            source=linked[int(document)][0],
            size_bytes=int(size) if size is not None else None,
            added_on=added.date() if added is not None else None,
            storage_key=stored.get(int(document)),
        )
        for document, title, name, size, added, category in rows
    ]
    return sorted(out, key=lambda d: (d.added_on or date.min, d.document_id), reverse=True)


def tenant_person(session: Session, company_id: UUID, person_id: UUID) -> Person | None:
    return session.scalars(
        sa.select(Person).where(
            Person.id == person_id, Person.company_id == company_id, Person.kind == PersonKind.tenant
        )
    ).first()
