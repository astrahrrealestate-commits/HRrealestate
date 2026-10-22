"""Embedding step: fills only missing vectors, scoped, repeatable, and a provider outage leaves finished work done."""

from uuid import UUID

import pytest
from sqlalchemy import Engine, func, select
from sqlalchemy.orm import Session

from app.core.ids import new_id
from app.core.settings import EMBEDDING_DIMENSIONS, Settings
from app.db.models import Company, DocumentChunk, DocumentRow
from app.llm.embeddings import HashingEmbedder
from app.pipeline.document_embed import embed_chunks, embed_document, embed_documents_summary
from app.pipeline.documents import file_document
from app.storage.drive import MemoryDrive
from app.storage.extract import FakeExtractor
from app.storage.memory import MemoryStorage
from tests.integration.test_documents import _attachment, _doc

pytestmark = pytest.mark.integration
LEASE = (
    b"\fHuurovereenkomst\nHuurder: Anna de Vries\n\nArtikel 4 Waarborgsom\nDe waarborgsom is twee maanden kale huur."
)


@pytest.fixture
def settings(test_settings: Settings) -> Settings:
    return test_settings.model_copy(update={"llm_model": "fake"})


def _filed(engine: Engine, settings: Settings, cid: UUID) -> UUID:
    storage = MemoryStorage()
    att = _attachment(engine, cid, storage, "scan.pdf", "application/pdf", LEASE)
    file_document(engine, settings, storage, MemoryDrive(), cid, att, extractor=FakeExtractor())
    return _doc(engine, att).id


def _missing(engine: Engine, cid: UUID) -> int:
    with Session(engine) as s:
        q = (
            select(func.count())
            .select_from(DocumentChunk)
            .where(DocumentChunk.company_id == cid, DocumentChunk.embedding.is_(None))
        )
        return int(s.scalar(q) or 0)


def test_filing_leaves_vectors_to_the_embed_step_which_fills_them(
    migrated_engine: Engine, settings: Settings, committed_company: Company
) -> None:
    cid = committed_company.id
    doc_id = _filed(migrated_engine, settings, cid)
    assert _missing(migrated_engine, cid) >= 1
    assert embed_document(migrated_engine, HashingEmbedder(), cid, doc_id) >= 2  # its chunk(s) and its own vector
    assert _missing(migrated_engine, cid) == 0
    with Session(migrated_engine) as s:
        doc = s.get(DocumentRow, doc_id)
        assert doc is not None
        assert doc.doc_embedding is not None
        assert len(doc.doc_embedding) == EMBEDDING_DIMENSIONS
        chunk = s.scalars(select(DocumentChunk).where(DocumentChunk.document_id == doc_id)).first()
        assert chunk is not None
        assert chunk.embedding is not None
        assert len(chunk.embedding) == EMBEDDING_DIMENSIONS


def test_a_second_run_changes_nothing(migrated_engine: Engine, settings: Settings, committed_company: Company) -> None:
    cid = committed_company.id
    doc_id = _filed(migrated_engine, settings, cid)
    embed_document(migrated_engine, HashingEmbedder(), cid, doc_id)
    assert embed_document(migrated_engine, HashingEmbedder(), cid, doc_id) == 0


def test_the_embedded_text_is_the_header_plus_the_chunk(
    migrated_engine: Engine, settings: Settings, committed_company: Company
) -> None:
    cid = committed_company.id
    seen: list[str] = []

    class Spy(HashingEmbedder):
        def embed_documents(self, texts):  # type: ignore[no-untyped-def]
            seen.extend(texts)
            return super().embed_documents(texts)

    doc_id = _filed(migrated_engine, settings, cid)
    embed_chunks(migrated_engine, Spy(), cid, doc_id)
    assert seen
    assert seen[0].startswith("Lease agreement (lease,")
    assert "waarborgsom is twee maanden" in seen[0]


def test_only_the_asked_company_is_embedded(
    migrated_engine: Engine, settings: Settings, committed_company: Company
) -> None:
    cid = committed_company.id
    _filed(migrated_engine, settings, cid)
    assert embed_chunks(migrated_engine, HashingEmbedder(), new_id()) == 0
    assert embed_documents_summary(migrated_engine, HashingEmbedder(), new_id()) == 0
    assert _missing(migrated_engine, cid) >= 1


def test_a_provider_outage_propagates_and_a_rerun_finishes(
    migrated_engine: Engine, settings: Settings, committed_company: Company
) -> None:
    cid = committed_company.id
    doc_id = _filed(migrated_engine, settings, cid)

    class Down(HashingEmbedder):
        def embed_documents(self, texts):  # type: ignore[no-untyped-def]
            raise ConnectionError("provider down")

    with pytest.raises(ConnectionError):
        embed_document(migrated_engine, Down(), cid, doc_id)
    assert _missing(migrated_engine, cid) >= 1
    embed_document(migrated_engine, HashingEmbedder(), cid, doc_id)
    assert _missing(migrated_engine, cid) == 0
