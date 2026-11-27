"""A stored BRIXX document becomes a library document (M13): read, chunked and linked to its people, lease and units,
so dossiers (case scope: case, lease, main person) and Astra's search find it like a filed attachment.

Never read: identity papers and other sensitive kinds by BRIXX's own label or the title, and any text that reads like
an identity document; documents of a relatie erased under GDPR. Those, and files without text (scans: no OCR here),
get a `skipped` row, so the backlog never tries them again. A newer version of a document replaces the older one.
"""

import re
from dataclasses import dataclass
from datetime import date
from uuid import UUID

from sqlalchemy import Engine, delete, select
from sqlalchemy.orm import Session

from app.contracts import DocType
from app.core.logging import get_logger
from app.db.enums import BrixxDocumentStatus, DocLinkKind, DocumentStatus
from app.db.models import DocumentLink, DocumentRow
from app.db.models.brixx import BrixxDocument
from app.pipeline.document_index import write_chunks
from app.pipeline.document_policy import looks_like_id_text
from app.pipeline.injection_scan import scan
from app.storage.extract import TextExtractor
from app.storage.ports import ObjectStorage

log = get_logger(__name__)
LINK_METHOD = "brixx"
# Identity, income, bank and health papers: the tenant's, but never draft context.
SENSITIVE = re.compile(
    r"identiteit|legitimatie|paspoort|passport|rijbewijs|id[- ]?(kaart|bewijs)|verblijf|\bbsn\b|loon|salaris|"
    r"inkomen|werkgever|bankafschrift|bank ?statement|bkr|medisch|zorg|screening|krediet|uittreksel",
    re.IGNORECASE,
)
_TYPES = (
    (re.compile(r"huurovereenkomst|huurcontract|contract|lease|allonge|addendum", re.I), DocType.lease),
    (re.compile(r"factuur|invoice|nota\b", re.I), DocType.invoice),
    (re.compile(r"offerte|quote|begroting", re.I), DocType.quote),
    (re.compile(r"verzekering|polis|insurance", re.I), DocType.insurance),
    (re.compile(r"certificaat|keuring|energielabel|attest|inspectie|opleverrapport", re.I), DocType.certificate),
    (re.compile(r"brief|correspondentie|letter|e-?mail", re.I), DocType.correspondence),
)


@dataclass(frozen=True)
class BrixxDocInput:
    brixx_row_id: UUID  # brixx_documents.id of the stored version
    title: str
    file_name: str
    kinds: tuple[str, ...]
    added_on: date | None
    erased: bool
    person_ids: tuple[UUID, ...]
    lease_ids: tuple[UUID, ...]
    unit_ids: tuple[UUID, ...]


def doc_type_of(d: BrixxDocInput) -> DocType:
    words = " ".join([*d.kinds, d.title, d.file_name])
    return next((kind for pattern, kind in _TYPES if pattern.search(words)), DocType.other)


def _why_not(d: BrixxDocInput) -> str | None:
    if d.erased:
        return "erased relatie"
    if any(SENSITIVE.search(k) for k in (*d.kinds, d.title, d.file_name)):
        return "sensitive kind"
    return None


def _row(company_id: UUID, d: BrixxDocInput, status: DocumentStatus, why: str | None, suspicious: bool) -> DocumentRow:
    return DocumentRow(
        company_id=company_id, brixx_document_id=d.brixx_row_id, doc_type=doc_type_of(d).value, title=d.title,
        file_name=d.file_name, confidence=1.0, status=status, document_date=d.added_on, error=why,
        suspicious=suspicious,
    )  # fmt: skip


def _newer_exists(session: Session, company_id: UUID, stored: BrixxDocument) -> bool:
    """An older version is never indexed over a newer one (ids are UUIDv7: later ids are newer rows)."""
    newer = select(BrixxDocument.id).where(
        BrixxDocument.company_id == company_id,
        BrixxDocument.document_id == stored.document_id,
        BrixxDocument.status == BrixxDocumentStatus.stored,
        BrixxDocument.id > stored.id,
    )
    return session.scalar(newer.limit(1)) is not None


def _replace_older(session: Session, company_id: UUID, stored: BrixxDocument) -> None:
    """Library rows of the document's other versions go (their chunks and links cascade)."""
    others = select(BrixxDocument.id).where(
        BrixxDocument.company_id == company_id,
        BrixxDocument.document_id == stored.document_id,
        BrixxDocument.id != stored.id,
    )
    session.execute(
        delete(DocumentRow).where(DocumentRow.company_id == company_id, DocumentRow.brixx_document_id.in_(others))
    )


def _links(company_id: UUID, doc_id: UUID, d: BrixxDocInput) -> list[DocumentLink]:
    refs = [(DocLinkKind.person, i) for i in d.person_ids] + [(DocLinkKind.lease, i) for i in d.lease_ids]
    refs += [(DocLinkKind.unit, i) for i in d.unit_ids]
    return [
        DocumentLink(company_id=company_id, document_id=doc_id, kind=kind, ref_id=ref, method=LINK_METHOD, score=1.0)
        for kind, ref in refs
    ]


def _text(storage: ObjectStorage, extractor: TextExtractor, stored: BrixxDocument, d: BrixxDocInput) -> str | None:
    if not stored.storage_key:
        return None
    ex = extractor.extract(storage.get(stored.storage_key), stored.content_type or "application/pdf", d.file_name)
    return (ex.text or "").strip() or None


def add_brixx_document(
    engine: Engine, storage: ObjectStorage, extractor: TextExtractor, company_id: UUID, d: BrixxDocInput
) -> DocumentStatus | None:
    """The library row's status; None when this version already has one (or is not a stored version)."""
    with Session(engine) as session:
        stored = session.scalar(
            select(BrixxDocument).where(BrixxDocument.company_id == company_id, BrixxDocument.id == d.brixx_row_id)
        )
        done = session.scalar(select(DocumentRow.id).where(DocumentRow.brixx_document_id == d.brixx_row_id))
        if stored is None or done is not None or _newer_exists(session, company_id, stored):
            return None
        session.expunge(stored)
    why = _why_not(d)
    text = None if why else _text(storage, extractor, stored, d)
    if why is None and text is None:
        why = "no text"
    elif text is not None and looks_like_id_text(text):
        why, text = "identity document", None
    with Session(engine) as session, session.begin():
        _replace_older(session, company_id, stored)
        status = DocumentStatus.skipped if text is None else DocumentStatus.filed
        doc = _row(company_id, d, status, why, suspicious=bool(text and scan(text)))
        session.add(doc)
        session.flush()
        links = _links(company_id, doc.id, d) if text is not None else []
        if text is not None:
            write_chunks(session, doc, text, None)
            session.add_all(links)
    log.info("brixx_library.indexed", status=status.value, reason=why, links=len(links))
    return status
