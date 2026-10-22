"""Backfill of documents filed before M10: read, chunk, link; idempotent; unreadable ones are marked once."""

from uuid import UUID

import pytest
from sqlalchemy import Engine, func, select
from sqlalchemy.orm import Session

from app.core.settings import Settings
from app.db.models import Company, DocumentChunk, DocumentRow
from app.pipeline.document_backfill import Outcome, backfill_document, unread_ids
from app.pipeline.documents import file_document
from app.storage.drive import MemoryDrive
from app.storage.extract import FakeExtractor
from app.storage.memory import MemoryStorage
from tests.integration.test_documents import _attachment, _doc

pytestmark = pytest.mark.integration
LEASE = b"Huurovereenkomst\nHuurder: Anna de Vries\nWaarborgsom: twee maanden huur"


@pytest.fixture
def settings(test_settings: Settings) -> Settings:
    return test_settings.model_copy(update={"llm_model": "fake"})


def _filed_the_old_way(engine: Engine, settings: Settings, storage: MemoryStorage, cid: UUID, data: bytes) -> UUID:
    """Filed from metadata only (no extractor), as before M10."""
    att = _attachment(engine, cid, storage, "huurcontract.pdf", "application/pdf", data)
    file_document(engine, settings, storage, MemoryDrive(), cid, att)
    return att


def _chunks(engine: Engine, cid: UUID) -> int:
    with Session(engine) as s:
        return int(
            s.scalar(select(func.count()).select_from(DocumentChunk).where(DocumentChunk.company_id == cid)) or 0
        )


def test_backfill_reads_an_old_document_once(
    migrated_engine: Engine, settings: Settings, committed_company: Company
) -> None:
    cid, storage = committed_company.id, MemoryStorage()
    att = _filed_the_old_way(migrated_engine, settings, storage, cid, LEASE)
    assert _doc(migrated_engine, att).facts is None
    assert unread_ids(migrated_engine, cid) == [att]
    assert backfill_document(migrated_engine, settings, storage, FakeExtractor(), cid, att) is Outcome.read
    row = _doc(migrated_engine, att)
    assert (row.reader_version, row.doc_type) == ("v1", "lease")  # filing decision untouched
    assert row.facts is not None
    assert row.summary
    assert _chunks(migrated_engine, cid) == 1
    assert unread_ids(migrated_engine, cid) == []
    backfill_document(migrated_engine, settings, storage, FakeExtractor(), cid, att)
    assert _chunks(migrated_engine, cid) == 1


def test_an_unreadable_document_is_marked_so_it_is_not_retried_forever(
    migrated_engine: Engine, settings: Settings, committed_company: Company
) -> None:
    cid, storage = committed_company.id, MemoryStorage()
    att = _filed_the_old_way(migrated_engine, settings, storage, cid, LEASE)
    off = settings.model_copy(update={"doc_read_content": False})
    assert backfill_document(migrated_engine, off, storage, FakeExtractor(), cid, att) is Outcome.unreadable
    assert _doc(migrated_engine, att).reader_version == "none"
    assert unread_ids(migrated_engine, cid) == []


def test_id_documents_are_not_candidates(
    migrated_engine: Engine, settings: Settings, committed_company: Company
) -> None:
    cid, storage = committed_company.id, MemoryStorage()
    att = _attachment(migrated_engine, cid, storage, "paspoort.pdf", "application/pdf", b"Paspoort 1")
    file_document(migrated_engine, settings, storage, MemoryDrive(), cid, att)
    with Session(migrated_engine) as s:
        assert s.scalars(select(DocumentRow.doc_type).where(DocumentRow.company_id == cid)).one() == "id_document"
    assert unread_ids(migrated_engine, cid) == []


def test_company_scoping(migrated_engine: Engine, settings: Settings, committed_company: Company) -> None:
    from app.core.ids import new_id

    cid, storage = committed_company.id, MemoryStorage()
    _filed_the_old_way(migrated_engine, settings, storage, cid, LEASE)
    assert unread_ids(migrated_engine, new_id()) == []


def test_a_budget_stop_leaves_the_document_unread_for_a_later_run(
    migrated_engine: Engine, settings: Settings, committed_company: Company
) -> None:
    cid, storage = committed_company.id, MemoryStorage()
    att = _filed_the_old_way(migrated_engine, settings, storage, cid, LEASE)
    capped = settings.model_copy(update={"llm_daily_calls_cap": 0})
    assert backfill_document(migrated_engine, capped, storage, FakeExtractor(), cid, att) is Outcome.budget
    assert _doc(migrated_engine, att).reader_version is None
    assert unread_ids(migrated_engine, cid) == [att]  # picked up again once there is budget
    assert backfill_document(migrated_engine, settings, storage, FakeExtractor(), cid, att) is Outcome.read


def test_a_poison_document_is_marked_and_skipped(migrated_engine: Engine, settings: Settings,
                                                 committed_company: Company) -> None:  # fmt: skip
    from app.pipeline.document_backfill import mark_unreadable

    cid, storage = committed_company.id, MemoryStorage()
    att = _filed_the_old_way(migrated_engine, settings, storage, cid, LEASE)
    mark_unreadable(migrated_engine, cid, att, "error")
    assert _doc(migrated_engine, att).reader_version == "error"
    assert unread_ids(migrated_engine, cid) == []
