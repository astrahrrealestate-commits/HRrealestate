"""#9 Backfill (M10): read, chunk and link documents filed before content reading existed.

One document at a time, idempotent: a document that already has a `reader_version` is skipped, extraction is cached on
the attachment, chunks are insert-or-ignore. Nothing is re-filed or moved here; moving is the reorg plan's job.
A document that cannot be read keeps its metadata decision untouched.
"""

from enum import StrEnum
from uuid import UUID

from sqlalchemy import Engine, select, update
from sqlalchemy.orm import Session

from app.core.settings import Settings
from app.db.enums import DocumentStatus
from app.db.models import AttachmentRow, DocumentRow
from app.pipeline.document_embed import unit_label_of
from app.pipeline.document_index import INDEX_VERSION, write_chunks
from app.pipeline.document_links import link_document
from app.pipeline.document_policy import looks_like_id
from app.pipeline.document_reading import Reading, ReadInput, Unread, facts_columns, read_document
from app.pipeline.documents import load_filing
from app.storage.extract import TextExtractor
from app.storage.ports import ObjectStorage

BATCH = 10
_TARGETS = (DocumentStatus.filed, DocumentStatus.review)


def unread_ids(engine: Engine, company_id: UUID, limit: int = BATCH) -> list[UUID]:
    with Session(engine) as session:
        return list(session.scalars(
            select(DocumentRow.attachment_id)
            .where(DocumentRow.company_id == company_id, DocumentRow.status.in_(_TARGETS),
                   DocumentRow.reader_version.is_(None), DocumentRow.doc_type != "id_document")
            .order_by(DocumentRow.created_at).limit(limit)
        ))  # fmt: skip


class Outcome(StrEnum):
    read = "read"
    unreadable = "unreadable"  # marked `none`: nothing readable, or the reader refused; not retried
    budget = "budget"  # left untouched: the LLM budget is spent, a later run reads it


def mark_unreadable(engine: Engine, company_id: UUID, attachment_id: UUID, marker: str) -> None:
    """`none` (nothing to read) or `error` (a permanent problem with this one document): it is skipped from now on."""
    with Session(engine) as session, session.begin():
        session.execute(
            update(DocumentRow)
            .where(DocumentRow.attachment_id == attachment_id, DocumentRow.company_id == company_id)
            .values(reader_version=marker)
        )


def backfill_document(engine: Engine, settings: Settings, storage: ObjectStorage, extractor: TextExtractor,
                      company_id: UUID, attachment_id: UUID) -> Outcome:  # fmt: skip
    f = load_filing(engine, company_id, attachment_id)
    m = f.meta
    reading: Reading | Unread = Unread.no_text
    if settings.doc_read_content and not looks_like_id(m):
        given = ReadInput(company_id, attachment_id, m.filename, m.mime_type, m.size_bytes, f.party, f.message_text,
                          f.case_summary)  # fmt: skip
        reading = read_document(engine, settings, storage, extractor, given)
    if reading is Unread.budget:
        return Outcome.budget
    if isinstance(reading, Unread):
        mark_unreadable(engine, company_id, attachment_id, "none")
        link_document(engine, company_id, attachment_id)
        return Outcome.unreadable
    mine = (DocumentRow.attachment_id == attachment_id) & (DocumentRow.company_id == company_id)
    with Session(engine) as session, session.begin():
        session.execute(update(DocumentRow).where(mine).values(**facts_columns(reading)))
    link_document(engine, company_id, attachment_id)  # before the chunks: their header names the unit it finds
    with Session(engine) as session, session.begin():
        row = session.scalar(select(DocumentRow).where(mine))
        if row is not None and reading.text:
            write_chunks(session, row, reading.text, unit_label_of(session, company_id, row.id))
    return Outcome.read


def stale_ids(engine: Engine, company_id: UUID, limit: int = BATCH) -> list[UUID]:
    """Documents with readable text whose chunks were made by an older recipe (or not at all)."""
    with Session(engine) as session:
        return list(session.scalars(
            select(DocumentRow.id)
            .join(AttachmentRow, AttachmentRow.id == DocumentRow.attachment_id)
            .where(DocumentRow.company_id == company_id, DocumentRow.status.in_(_TARGETS),
                   AttachmentRow.extracted_text.is_not(None),
                   (DocumentRow.index_version.is_(None)) | (DocumentRow.index_version != INDEX_VERSION))
            .order_by(DocumentRow.created_at).limit(limit)
        ))  # fmt: skip


def reindex_document(engine: Engine, company_id: UUID, document_id: UUID) -> int:
    """Rebuild one document's chunks with the current recipe (headings, pages, overlap, header with today's unit).
    Vectors are cleared; the embed step refills them. Returns the number of chunks."""
    with Session(engine) as session, session.begin():
        doc = session.scalar(
            select(DocumentRow).where(DocumentRow.id == document_id, DocumentRow.company_id == company_id)
        )
        text = (
            session.scalar(
                select(AttachmentRow.extracted_text).where(
                    AttachmentRow.id == doc.attachment_id, AttachmentRow.company_id == company_id
                )
            )
            if doc
            else None
        )
        if doc is None or not text:
            return 0
        return write_chunks(session, doc, text, unit_label_of(session, company_id, document_id))
