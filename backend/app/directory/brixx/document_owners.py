"""Who a BRIXX document belongs to, in our directory's ids (M13): the inverse of `tenant_documents`.

A document hangs on a relatie (`PRG_RELATIEDOCUMENT`, or `PRG_DOCUMENT_LINK` type 10), a contract (9), a unit
(subobject, 12) or a building (object, 11). Relaties map to people by `brixx_ref`; contracts to leases (`"<contract>:"`
refs) and the people on them; units and buildings to our units. A relatie erased under GDPR makes the whole document
off limits. Reads the mirror for one company with indexed filters; a lookup table BRIXX does not list reads as empty.
"""

from dataclasses import dataclass, field
from datetime import date
from typing import Any
from uuid import UUID

import psycopg.errors
import sqlalchemy as sa
from sqlalchemy.exc import ProgrammingError
from sqlalchemy.orm import Session

from app.db.brixx_erasure import erased_relatie_ids, mirror_table
from app.db.models import Lease, LeaseParty, Person, Unit
from app.directory.brixx.tenant_documents import (
    DOCUMENT,
    DOCUMENT_CATEGORY,
    DOCUMENT_LINK,
    LINK_CONTRACT,
    LINK_OBJECT,
    LINK_RELATIE,
    LINK_SUBOBJECT,
    RELATIE_DOCUMENT,
    RELATIE_DOCUMENT_TYPE,
    SUBOBJECT_TABLE,
)

_BIGINT, _TEXT, _SMALL = sa.BigInteger(), sa.Text(), sa.SmallInteger()


@dataclass(frozen=True)
class BrixxDocMeta:
    title: str
    file_name: str
    kinds: tuple[str, ...]  # BRIXX's category and relatie-document labels ("Contracten", "Identiteitsbewijs")
    added_on: date | None
    erased: bool = False  # linked to a relatie erased under GDPR
    person_ids: tuple[UUID, ...] = ()
    lease_ids: tuple[UUID, ...] = ()
    unit_ids: tuple[UUID, ...] = ()
    entities: dict[int, list[int]] = field(default_factory=dict)


def _rows(session: Session, query: sa.Executable) -> list[Any]:
    """The query's rows; none when the mirror lacks one of its tables (BRIXX does not list every lookup table)."""
    try:
        with session.begin_nested():
            return list(session.execute(query).all())
    except ProgrammingError as exc:
        if isinstance(exc.orig, psycopg.errors.UndefinedTable | psycopg.errors.InvalidSchemaName):
            return []
        raise


def _t(name: str, *columns: tuple[str, sa.types.TypeEngine[Any]]) -> sa.Table:
    return mirror_table(name, *(sa.Column(n, kind) for n, kind in columns), sa.Column("_deleted_at", sa.DateTime(True)))


def _labels(session: Session, table: str, key: str, ids: set[int]) -> list[str]:
    if not ids:
        return []
    t = _t(table, (key, _BIGINT), ("benaming", _TEXT))
    return [str(r[0]) for r in _rows(session, sa.select(t.c.benaming).where(t.c[key].in_(ids))) if r[0]]


def _links(session: Session, company_id: UUID, document_id: int) -> dict[int, list[int]]:
    link = _t(DOCUMENT_LINK, ("prg_documentid", _BIGINT), ("entiteitid", _BIGINT), ("sys_entiteittypeid", _BIGINT))
    query = sa.select(link.c.sys_entiteittypeid, link.c.entiteitid).where(
        link.c.company_id == company_id, link.c.prg_documentid == document_id, link.c._deleted_at.is_(None)
    )
    found: dict[int, list[int]] = {}
    for kind, entity in _rows(session, query):
        if kind is not None and entity is not None:
            found.setdefault(int(kind), []).append(int(entity))
    return found


def _entities(session: Session, company_id: UUID, document_id: int) -> tuple[dict[int, list[int]], list[str]]:
    """Linked entity ids by link type, and BRIXX's relatie-document labels."""
    found = _links(session, company_id, document_id)
    own = _t(
        RELATIE_DOCUMENT,
        ("prg_documentid", _BIGINT),
        ("prg_relatieid", _BIGINT),
        ("typ_relatiedocumentid", _BIGINT),
        ("indverwijderd", _SMALL),
    )
    query = sa.select(own.c.prg_relatieid, own.c.typ_relatiedocumentid).where(
        own.c.company_id == company_id,
        own.c.prg_documentid == document_id,
        own.c._deleted_at.is_(None),
        sa.func.coalesce(own.c.indverwijderd, 0) == 0,
    )
    kinds: set[int] = set()
    for relatie, kind in _rows(session, query):
        if relatie is not None:
            found.setdefault(LINK_RELATIE, []).append(int(relatie))
        if kind is not None:
            kinds.add(int(kind))
    return found, _labels(session, RELATIE_DOCUMENT_TYPE, "typ_relatiedocumentid", kinds)


def _units_of_buildings(session: Session, company_id: UUID, objects: list[int]) -> list[str]:
    if not objects:
        return []
    sub = _t(SUBOBJECT_TABLE, ("prg_subobjectid", _BIGINT), ("prg_objectid", _BIGINT))
    query = sa.select(sub.c.prg_subobjectid).where(
        sub.c.company_id == company_id, sub.c.prg_objectid.in_(objects), sub.c._deleted_at.is_(None)
    )
    return [str(r[0]) for r in _rows(session, query) if r[0] is not None]


def _ids(session: Session, query: sa.Select[Any]) -> set[UUID]:
    return set(session.scalars(query))


def _directory(
    session: Session, company_id: UUID, found: dict[int, list[int]]
) -> tuple[set[UUID], set[UUID], set[UUID]]:
    relaties = [str(r) for r in found.get(LINK_RELATIE, [])]
    people: set[UUID] = set()
    if relaties:
        people = _ids(
            session, sa.select(Person.id).where(Person.company_id == company_id, Person.brixx_ref.in_(relaties))
        )
    leases: set[UUID] = set()
    for contract in found.get(LINK_CONTRACT, []):
        query = sa.select(Lease.id).where(Lease.company_id == company_id, Lease.brixx_ref.like(f"{contract}:%"))
        leases |= _ids(session, query)
    if leases:
        parties = sa.select(LeaseParty.person_id).where(
            LeaseParty.company_id == company_id, LeaseParty.lease_id.in_(leases)
        )
        people |= _ids(session, parties)
    refs = [str(u) for u in found.get(LINK_SUBOBJECT, [])]
    refs += _units_of_buildings(session, company_id, found.get(LINK_OBJECT, []))
    units: set[UUID] = set()
    if refs:
        units = _ids(session, sa.select(Unit.id).where(Unit.company_id == company_id, Unit.brixx_ref.in_(refs)))
    return people, leases, units


def document_owners(session: Session, company_id: UUID, document_id: int) -> BrixxDocMeta | None:
    """The document's metadata and owners; None when the mirror no longer lists it."""
    doc = _t(
        DOCUMENT,
        ("prg_documentid", _BIGINT),
        ("benaming", _TEXT),
        ("filenaam", _TEXT),
        ("typ_documentcategorieid", _BIGINT),
        ("newdatetime", sa.DateTime(True)),
    )
    query = sa.select(doc.c.benaming, doc.c.filenaam, doc.c.newdatetime, doc.c.typ_documentcategorieid).where(
        doc.c.company_id == company_id, doc.c.prg_documentid == document_id, doc.c._deleted_at.is_(None)
    )
    rows = _rows(session, query)
    if not rows:
        return None
    title, name, added, category_id = rows[0]
    wanted = {int(category_id)} if category_id is not None else set()
    category = _labels(session, DOCUMENT_CATEGORY, "typ_documentcategorieid", wanted)
    found, labels = _entities(session, company_id, document_id)
    erased = bool(set(found.get(LINK_RELATIE, [])) & erased_relatie_ids(session, company_id))
    people, leases, units = _directory(session, company_id, found)
    return BrixxDocMeta(
        title=(title or name or f"Document {document_id}").strip()[:200],
        file_name=(name or title or f"document-{document_id}").strip()[:255],
        kinds=tuple(k for k in (*category, *labels) if k),
        added_on=added.date() if added else None,
        erased=erased,
        person_ids=tuple(sorted(people)),
        lease_ids=tuple(sorted(leases)),
        unit_ids=tuple(sorted(units)),
        entities=found,
    )
