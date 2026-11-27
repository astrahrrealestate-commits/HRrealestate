"""BRIXX documents into the document library (M13): right after a version is stored, and as a backlog on each sync.

Joins the directory (who a document belongs to) and the pipeline (reading, chunking, linking): neither may import
the other. Idempotent: a version with a library row is never indexed again. Embeddings follow through the same
`embed_chunks` the filing pipeline uses; a provider problem leaves them for the embed backfill.
"""

from uuid import UUID

from sqlalchemy import Engine, select
from sqlalchemy.dialects.postgresql import distinct_on
from sqlalchemy.orm import Session

from app.core.logging import get_logger
from app.db.enums import BrixxDocumentStatus
from app.db.models import DocumentRow
from app.db.models.brixx import BrixxDocument
from app.directory.brixx.document_owners import document_owners
from app.llm.embeddings import TextEmbedder
from app.pipeline.brixx_library import BrixxDocInput, add_brixx_document
from app.pipeline.document_embed import embed_chunks
from app.storage.extract import TextExtractor
from app.storage.ports import ObjectStorage

log = get_logger(__name__)
BACKLOG_PER_RUN = 40


def _input(engine: Engine, company_id: UUID, row_id: UUID) -> BrixxDocInput | None:
    with Session(engine) as session:
        stored = session.scalar(
            select(BrixxDocument).where(
                BrixxDocument.company_id == company_id,
                BrixxDocument.id == row_id,
                BrixxDocument.status == BrixxDocumentStatus.stored,
            )
        )
        meta = document_owners(session, company_id, stored.document_id) if stored is not None else None
    if meta is None:
        return None
    return BrixxDocInput(
        brixx_row_id=row_id, title=meta.title, file_name=meta.file_name, kinds=meta.kinds, added_on=meta.added_on,
        erased=meta.erased, person_ids=meta.person_ids, lease_ids=meta.lease_ids, unit_ids=meta.unit_ids,
    )  # fmt: skip


def index_brixx_document(
    engine: Engine, storage: ObjectStorage, extractor: TextExtractor, embedder: TextEmbedder | None, company_id: UUID,
    row_id: UUID,
) -> bool:  # fmt: skip
    """Whether this stored version got a library row now."""
    d = _input(engine, company_id, row_id)
    if d is None:
        return False
    status = add_brixx_document(engine, storage, extractor, company_id, d)
    if status is None:
        return False
    if embedder is not None:
        try:
            embed_chunks(engine, embedder, company_id)
        except Exception as exc:  # the embed backfill fills what a provider outage left
            log.warning("brixx_library.embed_failed", error_type=type(exc).__name__)
    return True


def unindexed(engine: Engine, company_id: UUID, limit: int = BACKLOG_PER_RUN) -> list[UUID]:
    """The newest stored version of each document, where it has no library row yet."""
    with Session(engine) as session:
        indexed = select(DocumentRow.brixx_document_id).where(
            DocumentRow.company_id == company_id, DocumentRow.brixx_document_id.is_not(None)
        )
        newest = (  # UUIDv7 ids: the highest id is the newest version of each document
            select(BrixxDocument.id)
            .ext(distinct_on(BrixxDocument.document_id))
            .where(BrixxDocument.company_id == company_id, BrixxDocument.status == BrixxDocumentStatus.stored)
            .order_by(BrixxDocument.document_id, BrixxDocument.id.desc())
            .subquery()
        )
        rows = session.scalars(
            select(newest.c.id).where(newest.c.id.not_in(indexed)).order_by(newest.c.id).limit(limit)
        )
        return list(rows)


def unindexed_version(engine: Engine, company_id: UUID, document_id: int) -> UUID | None:
    """The newest stored version of one document, when it has no library row yet."""
    with Session(engine) as session:
        newest = session.scalar(
            select(BrixxDocument.id)
            .where(
                BrixxDocument.company_id == company_id,
                BrixxDocument.document_id == document_id,
                BrixxDocument.status == BrixxDocumentStatus.stored,
            )
            .order_by(BrixxDocument.id.desc())
            .limit(1)
        )
        done = session.scalar(select(DocumentRow.id).where(DocumentRow.brixx_document_id == newest)) if newest else None
    return newest if newest is not None and done is None else None


def index_backlog(
    engine: Engine, storage: ObjectStorage, extractor: TextExtractor, embedder: TextEmbedder | None, company_id: UUID,
    limit: int = BACKLOG_PER_RUN,
) -> int:  # fmt: skip
    """Index up to `limit` stored versions; one broken file never stops the rest."""
    done = 0
    for row_id in unindexed(engine, company_id, limit):
        try:
            done += index_brixx_document(engine, storage, extractor, None, company_id, row_id)
        except Exception as exc:
            log.warning("brixx_library.index_failed", row_id=str(row_id), error_type=type(exc).__name__)
    if done and embedder is not None:
        try:
            embed_chunks(engine, embedder, company_id)
        except Exception as exc:
            log.warning("brixx_library.embed_failed", error_type=type(exc).__name__)
    return done
