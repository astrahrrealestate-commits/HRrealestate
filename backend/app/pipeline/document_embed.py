"""Embedding a document's chunks and summary (ADR 0008). Idempotent: only rows without a vector are filled.

Runs after filing, in its own workflow step, so an embedding provider outage never blocks filing or the
Postgres-first claim. Until vectors exist, retrieval uses words alone. A transient provider error propagates for the
DBOS step to retry; the chunks already done keep their vectors.
"""

from uuid import UUID

from sqlalchemy import Engine, select, update
from sqlalchemy.orm import Session

from app.db.enums import DocLinkKind
from app.db.models import DocumentChunk, DocumentLink, DocumentRow, Unit
from app.llm.embeddings import TextEmbedder
from app.pipeline.document_index import header_for

BATCH = 64


def chunk_input(context: str | None, text: str) -> str:
    """What is embedded for a chunk: its header and its text, the same pair the full-text index sees."""
    return f"{context}\n{text}" if context else text


def unit_label_of(session: Session, company_id: UUID, document_id: UUID) -> str | None:
    ref = session.scalar(
        select(DocumentLink.ref_id)
        .where(DocumentLink.company_id == company_id, DocumentLink.document_id == document_id,
               DocumentLink.kind == DocLinkKind.unit, DocumentLink.method != "removed")
        .order_by(DocumentLink.score.desc()).limit(1)
    )  # fmt: skip
    return session.scalar(select(Unit.label).where(Unit.id == ref, Unit.company_id == company_id)) if ref else None


def doc_input(doc: DocumentRow, unit_label: str | None) -> str:
    """What is embedded for the document itself: what it is, who and where it is about, and its summary."""
    h = header_for(doc, unit_label)
    return f"{h.line(None, None)}\n{doc.summary or ''}".strip()


def embed_chunks(engine: Engine, embedder: TextEmbedder, company_id: UUID, document_id: UUID | None = None,
                 limit: int = 256) -> int:  # fmt: skip
    """Embed up to `limit` chunks that have no vector yet; returns how many were filled."""
    with Session(engine) as session:
        query = select(DocumentChunk.id, DocumentChunk.context, DocumentChunk.text).where(
            DocumentChunk.company_id == company_id, DocumentChunk.embedding.is_(None)
        )
        if document_id is not None:
            query = query.where(DocumentChunk.document_id == document_id)
        todo = session.execute(query.order_by(DocumentChunk.created_at, DocumentChunk.ord).limit(limit)).all()
    done = 0
    for start in range(0, len(todo), BATCH):
        batch = todo[start : start + BATCH]
        vectors = embedder.embed_documents([chunk_input(ctx, text) for _, ctx, text in batch])
        with Session(engine) as session, session.begin():
            for (chunk_id, _, _), vector in zip(batch, vectors, strict=True):
                session.execute(
                    update(DocumentChunk)
                    .where(DocumentChunk.id == chunk_id, DocumentChunk.company_id == company_id)
                    .values(embedding=vector)
                )
        done += len(batch)
    return done


def embed_documents_summary(engine: Engine, embedder: TextEmbedder, company_id: UUID,
                            document_id: UUID | None = None, limit: int = 64) -> int:  # fmt: skip
    """Embed the document-level vector of documents that have none and are indexed."""
    with Session(engine) as session:
        query = select(DocumentRow).where(
            DocumentRow.company_id == company_id,
            DocumentRow.doc_embedding.is_(None),
            DocumentRow.index_version.is_not(None),
        )
        if document_id is not None:
            query = query.where(DocumentRow.id == document_id)
        docs = list(session.scalars(query.limit(limit)))
        inputs = [doc_input(d, unit_label_of(session, company_id, d.id)) for d in docs]
        read = [(d.id, d.index_version) for d in docs]
    if not read:
        return 0
    vectors = embedder.embed_documents(inputs)
    done = 0
    with Session(engine) as session, session.begin():
        for (doc_id, version), vector in zip(read, vectors, strict=True):
            # only if nobody re-indexed the document meanwhile: a stale vector must not be written back
            result = session.execute(
                update(DocumentRow)
                .where(DocumentRow.id == doc_id, DocumentRow.company_id == company_id,
                       DocumentRow.doc_embedding.is_(None), DocumentRow.index_version == version)
                .values(doc_embedding=vector)
            )  # fmt: skip
            done += int(result.rowcount)  # type: ignore[attr-defined]  # CursorResult from a DML statement
    return done


def embed_document(engine: Engine, embedder: TextEmbedder, company_id: UUID, document_id: UUID) -> int:
    """Everything one document still lacks: chunk vectors, then its own."""
    n = embed_chunks(engine, embedder, company_id, document_id)
    return n + embed_documents_summary(engine, embedder, company_id, document_id)
