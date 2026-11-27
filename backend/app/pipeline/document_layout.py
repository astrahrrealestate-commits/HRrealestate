"""#9 Drive layout v2 (M10): `EstateOS/<unit>/<kind>/<year>/`, searchable Drive metadata, and where a document belongs.

v1 (`document_policy.folder_path`) filed by type and year only. v2 groups by property first, so everything about one
unit sits together: `EstateOS/Kerkstraat 12-2/Leases/2026/`. A document that cannot be placed in a unit goes to
`EstateOS/_Unsorted/<kind>/<year>/`; once a unit is known (a link the owner fixes, a directory import) the reorg
plan proposes the move. Folder names come from the directory, never from document text.
"""

import re
from dataclasses import dataclass
from datetime import date
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.contracts import DocType
from app.db.enums import DocLinkKind, PersonKind
from app.db.models import MessageRow, Person, Unit
from app.pipeline.document_links import resolve_links
from app.pipeline.document_policy import ROOT_FOLDER

LAYOUT_VERSION = "v2"
UNSORTED = "_Unsorted"
KIND_FOLDER = {
    DocType.lease: "Leases",
    DocType.invoice: "Invoices",
    DocType.quote: "Quotes",
    DocType.id_document: "ID documents",
    DocType.insurance: "Insurance",
    DocType.certificate: "Certificates",
    DocType.correspondence: "Correspondence",
    DocType.photo: "Photos",
    DocType.other: "Other",
}
MAX_FOLDER = 60
MAX_PROPERTY_BYTES = 100  # Drive: an app property's key and value together may use 124 bytes
_UNSAFE = re.compile(r"[\x00-\x1f\x7f/\\]")


@dataclass(frozen=True)
class Placement:
    unit_id: UUID | None
    unit_label: str | None
    tenant: str | None


def folder_name(label: str | None) -> str:
    """A unit label as one safe Drive folder name; nothing usable means `_Unsorted`."""
    cleaned = " ".join(_UNSAFE.sub(" ", label or "").split()).strip(" .")[:MAX_FOLDER].strip()
    return cleaned if cleaned and cleaned != UNSORTED else UNSORTED


def kind_folder(doc_type: str) -> str:
    try:
        return KIND_FOLDER[DocType(doc_type)]
    except ValueError:
        return KIND_FOLDER[DocType.other]


def folder_path_v2(doc_type: str, unit_label: str | None, day: date) -> tuple[str, ...]:
    return (ROOT_FOLDER, folder_name(unit_label), kind_folder(doc_type), str(day.year))


def _clip(value: str) -> str:
    return value.encode("utf-8")[:MAX_PROPERTY_BYTES].decode("utf-8", errors="ignore")


def drive_properties(
    doc_type: str, unit_label: str | None, party: str | None, day: date, sender: str | None = None
) -> dict[str, str]:
    """What Drive's own search can filter on (`appProperties`); short keys, values clipped to the byte limit."""
    props = {"doc_type": doc_type, "date": day.isoformat(), "layout": LAYOUT_VERSION}
    if unit_label:
        props["unit"] = _clip(unit_label)
    if party:
        props["party"] = _clip(party)
    if sender:
        props["sender"] = _clip(sender)
    return props


def description(title: str, summary: str | None) -> str:
    return " ".join((summary or title).split())[:400]


def placement(session: Session, company_id: UUID, message: MessageRow, facts: dict[str, Any] | None,
              document_date: date | None) -> Placement:  # fmt: skip
    """The unit and the tenant a new document belongs with, from the same evidence linking uses (nothing stored)."""
    links = resolve_links(session, company_id, message, facts, document_date).links
    units = sorted((x for x in links if x.kind is DocLinkKind.unit), key=lambda x: -x.score)
    people = sorted((x for x in links if x.kind is DocLinkKind.person), key=lambda x: -x.score)
    unit_id = units[0].ref_id if units else None
    label = (
        session.scalar(select(Unit.label).where(Unit.id == unit_id, Unit.company_id == company_id)) if unit_id else None
    )
    tenant = None
    if people:
        rows = session.execute(select(Person.id, Person.display_name).where(
            Person.company_id == company_id, Person.kind == PersonKind.tenant,
            Person.id.in_([x.ref_id for x in people]))).all()  # fmt: skip
        names = {pid: name for pid, name in rows}  # noqa: C416  (a mapping, not a copy of rows)
        tenant = next((names[x.ref_id] for x in people if x.ref_id in names), None)
    return Placement(unit_id, label, tenant)
