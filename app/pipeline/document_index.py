"""Indexing a document for retrieval (ADR 0008): chunks with page, heading and a contextual header, ready to embed.

The header ("Huurovereenkomst (lease, 2026-01-01) · Kerkstraat 12-2 · Anna de Vries · Artikel 4 Waarborgsom · p.2")
is stored in `context` and indexed with the chunk (full-text and vector), never shown as the chunk's own text. It keeps
"the deposit" in one lease apart from the same words in another. `index_version` records the recipe, so a change to it
(or to the document's unit) can be re-indexed by the backfill workflow.
"""

from dataclasses import dataclass
from datetime import date
from typing import Any

from sqlalchemy import delete, update
from sqlalchemy.orm import Session

from app.db.models import DocumentChunk, DocumentRow
from app.pipeline.document_chunks import PAGE_BREAK, chunk_document

INDEX_VERSION = "r2"
MAX_PARTIES = 3


@dataclass(frozen=True)
class DocHeader:
    title: str
    doc_type: str
    document_date: date | None
    unit_label: str | None
    parties: tuple[str, ...]

    def line(self, heading: str | None, page: int | None) -> str:
        head = f"{self.title} ({self.doc_type}, {self.document_date or 'undated'})"
        bits = [head, self.unit_label, ", ".join(self.parties) or None, heading, f"p.{page}" if page else None]
        return " · ".join(b for b in bits if b)


def header_for(doc: DocumentRow, unit_label: str | None) -> DocHeader:
    facts: dict[str, Any] = doc.facts or {}
    names = tuple(str(p["name"]) for p in facts.get("parties", []) if p.get("role") != "landlord")[:MAX_PARTIES]
    return DocHeader(doc.title, doc.doc_type, doc.document_date, unit_label, names)


def document_text_for_prompt(text: str) -> str:
    """The extracted text as a reader or model sees it: page breaks become blank lines."""
    return text.replace(PAGE_BREAK, "\n\n").strip()


def write_chunks(session: Session, doc: DocumentRow, text: str, unit_label: str | None) -> int:
    """Replace the document's chunks with the current recipe (embeddings are cleared: the embed step refills them)."""
    header = header_for(doc, unit_label)
    session.execute(
        delete(DocumentChunk).where(DocumentChunk.document_id == doc.id, DocumentChunk.company_id == doc.company_id)
    )
    rows = [
        DocumentChunk(
            company_id=doc.company_id, document_id=doc.id, ord=i, text=c.text, page=c.page, heading=c.heading,
            context=header.line(c.heading, c.page),
        )
        for i, c in enumerate(chunk_document(text))
    ]  # fmt: skip
    session.add_all(rows)
    session.execute(
        update(DocumentRow).where(DocumentRow.id == doc.id, DocumentRow.company_id == doc.company_id)
        .values(index_version=INDEX_VERSION, doc_embedding=None)
    )  # fmt: skip
    return len(rows)


def new_chunks_needed(doc: DocumentRow) -> bool:
    return doc.index_version != INDEX_VERSION
