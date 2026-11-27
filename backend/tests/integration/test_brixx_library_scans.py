"""Scanned BRIXX documents (M13): vision reads them, within their own daily cap, and never sensitive papers.

Synthetic mirror rows and files in memory storage (see test_brixx_library). Every name and byte is invented.
"""

from uuid import UUID

import pytest
from sqlalchemy import Engine, func, select
from sqlalchemy.orm import Session

from app.core.errors import AgentFailedError
from app.core.settings import Settings
from app.db.enums import DocumentStatus, ExtractionStatus
from app.db.models import DocumentChunk, DocumentRow, ModelCall
from app.db.models.brixx import BrixxDocument
from app.db.models.brixx_directory import BrixxErasedRef
from app.llm.budget import BRIXX_OCR_PURPOSE
from app.pipeline import brixx_library
from app.storage.extract import Extraction
from app.workflows.brixx_library import index_backlog, index_brixx_document, unindexed
from tests.integration.test_brixx_library import Reader, World, _store
from tests.integration.test_brixx_library import world as world  # the fixture
from tests.integration.test_tenant_documents import _doc, _link

pytestmark = pytest.mark.integration


class ScanReader:
    """A `SCAN` file is a scan: no text layer, vision reads it (the fake doc_ocr model strips the marker)."""

    def extract(self, data: bytes, mime_type: str, filename: str | None) -> Extraction:
        if data.startswith(b"SCAN"):
            return Extraction(ExtractionStatus.skipped, None, 1, "fake", needs_ocr=True, note="scan")
        return Reader().extract(data, mime_type, filename)


def _scan(engine: Engine, w: World, document_id: int, title: str, body: bytes) -> UUID:
    with Session(engine) as s, s.begin():
        _doc(s, w.company, document_id, title)
        _link(s, w.company, document_id, 9, 500)  # Anouk's contract
        return _store(s, w.storage, w.company, document_id, body)


def test_a_scanned_brixx_lease_is_read_through_vision(
    migrated_engine: Engine, world: World, test_settings: Settings
) -> None:
    row = _scan(migrated_engine, world, 20, "Huurovereenkomst scan", b"SCAN Allonge: de berging hoort bij Singel 5.")
    fake = test_settings.model_copy(update={"llm_model": "fake"})
    assert index_brixx_document(migrated_engine, world.storage, ScanReader(), None, world.company, row, fake)
    with Session(migrated_engine) as s:
        doc = s.scalars(select(DocumentRow).where(DocumentRow.brixx_document_id == row)).one()
        texts = " ".join(s.scalars(select(DocumentChunk.text).where(DocumentChunk.document_id == doc.id)))
        out = s.scalars(select(ModelCall.output).where(ModelCall.purpose == BRIXX_OCR_PURPOSE)).one()
    assert doc.status is DocumentStatus.filed
    assert "berging hoort bij Singel 5" in texts
    assert out is not None
    assert out["redacted"] is True  # the transcript lives on the library row only


def test_a_scanned_identity_paper_under_a_neutral_name_is_not_kept(
    migrated_engine: Engine, world: World, test_settings: Settings
) -> None:
    body = b"SCAN PASPOORT Nederland. Burgerservicenummer 123456782. Geboortedatum 01-02-1990."
    row = _scan(migrated_engine, world, 21, "Bijlage 3", body)
    fake = test_settings.model_copy(update={"llm_model": "fake"})
    index_brixx_document(migrated_engine, world.storage, ScanReader(), None, world.company, row, fake)
    with Session(migrated_engine) as s:
        doc = s.scalars(select(DocumentRow).where(DocumentRow.brixx_document_id == row)).one()
        chunks = " ".join(s.scalars(select(DocumentChunk.text).where(DocumentChunk.company_id == world.company)))
    assert (doc.status, doc.error) == (DocumentStatus.skipped, "identity document")
    assert "123456782" not in chunks


def test_a_scan_with_document_reading_off_is_not_sent_to_vision(
    migrated_engine: Engine, world: World, test_settings: Settings
) -> None:
    row = _scan(migrated_engine, world, 22, "Huurovereenkomst scan", b"SCAN Allonge.")
    off = test_settings.model_copy(update={"llm_model": "fake", "doc_read_content": False})
    index_brixx_document(migrated_engine, world.storage, ScanReader(), None, world.company, row, off)
    with Session(migrated_engine) as s:
        doc = s.scalars(select(DocumentRow).where(DocumentRow.brixx_document_id == row)).one()
        calls = s.scalar(select(func.count(ModelCall.id)).where(ModelCall.purpose == BRIXX_OCR_PURPOSE))
    assert (doc.status, doc.error, calls) == (DocumentStatus.skipped, "no text", 0)


def test_a_spent_budget_leaves_the_scan_for_the_next_sync_and_indexes_text_behind_it(
    migrated_engine: Engine, world: World, test_settings: Settings
) -> None:
    row = _scan(migrated_engine, world, 23, "Huurovereenkomst scan", b"SCAN Allonge.")
    with Session(migrated_engine) as s, s.begin():
        _doc(s, world.company, 29, "Huurovereenkomst addendum")
        _link(s, world.company, 29, 9, 500)
        behind = _store(s, world.storage, world.company, 29, b"Addendum: de berging hoort bij Singel 5.")
    spent = test_settings.model_copy(update={"llm_model": "fake", "llm_daily_calls_cap": 0})
    assert index_backlog(migrated_engine, world.storage, ScanReader(), None, world.company, spent) == 5
    assert _library_row(migrated_engine, row) is None
    assert _library_row(migrated_engine, behind) is not None  # a waiting scan never holds up a text document
    fake = test_settings.model_copy(update={"llm_model": "fake"})
    assert index_backlog(migrated_engine, world.storage, ScanReader(), None, world.company, fake) == 1


def test_the_download_step_leaves_a_scan_to_the_backlog(
    migrated_engine: Engine, world: World, test_settings: Settings
) -> None:
    row = _scan(migrated_engine, world, 19, "Huurovereenkomst scan", b"SCAN Allonge.")
    reader = ScanReader()
    with pytest.raises(brixx_library.ScanWaitsError):
        index_brixx_document(migrated_engine, world.storage, reader, None, world.company, row, world.settings,
                             vision=False)  # fmt: skip
    assert (_library_row(migrated_engine, row), _calls(migrated_engine)) == (None, 0)


def _fake(s: Settings, **extra: object) -> Settings:
    return s.model_copy(update={"llm_model": "fake", **extra})


def _calls(engine: Engine) -> int:
    with Session(engine) as s:
        return int(s.scalar(select(func.count(ModelCall.id)).where(ModelCall.purpose == BRIXX_OCR_PURPOSE)) or 0)


def _library_row(engine: Engine, row: UUID) -> DocumentRow | None:
    with Session(engine) as s:
        return s.scalar(select(DocumentRow).where(DocumentRow.brixx_document_id == row))


def test_a_sensitive_kind_scan_never_reaches_vision(
    migrated_engine: Engine, world: World, test_settings: Settings
) -> None:
    row = _scan(migrated_engine, world, 24, "Loonstrook scan", b"SCAN Nettoloon 2.400,00")
    index_brixx_document(migrated_engine, world.storage, ScanReader(), None, world.company, row, _fake(test_settings))
    doc = _library_row(migrated_engine, row)
    assert doc is not None
    assert (doc.status, doc.error, _calls(migrated_engine)) == (DocumentStatus.skipped, "sensitive kind", 0)


def test_a_scan_of_an_erased_relatie_never_reaches_vision(
    migrated_engine: Engine, world: World, test_settings: Settings
) -> None:
    with Session(migrated_engine) as s, s.begin():
        _doc(s, world.company, 25, "Brief")
        _link(s, world.company, 25, 10, 1)  # relatie 1 (Anouk)
        s.add(BrixxErasedRef(company_id=world.company, relatie_id=1))
        row = _store(s, world.storage, world.company, 25, b"SCAN Brief aan Anouk.")
    index_brixx_document(migrated_engine, world.storage, ScanReader(), None, world.company, row, _fake(test_settings))
    doc = _library_row(migrated_engine, row)
    assert doc is not None
    assert (doc.status, doc.error, _calls(migrated_engine)) == (DocumentStatus.skipped, "erased relatie", 0)


def test_payslip_or_bank_statement_text_under_a_neutral_name_is_not_kept(
    migrated_engine: Engine, world: World, test_settings: Settings
) -> None:
    row = _scan(migrated_engine, world, 26, "Bijlage 4", b"SCAN Salarisspecificatie mei. Loonheffing 312,00.")
    index_brixx_document(migrated_engine, world.storage, ScanReader(), None, world.company, row, _fake(test_settings))
    doc = _library_row(migrated_engine, row)
    with Session(migrated_engine) as s:
        chunks = " ".join(s.scalars(select(DocumentChunk.text).where(DocumentChunk.company_id == world.company)))
    assert doc is not None
    assert (doc.status, doc.error) == (DocumentStatus.skipped, "sensitive text")
    assert "Loonheffing" not in chunks


def test_scans_have_their_own_daily_cap(migrated_engine: Engine, world: World, test_settings: Settings) -> None:
    first = _scan(migrated_engine, world, 27, "Huurovereenkomst scan", b"SCAN Allonge een.")
    second = _scan(migrated_engine, world, 28, "Huurovereenkomst scan 2", b"SCAN Allonge twee.")
    capped = _fake(test_settings, brixx_ocr_daily_cap=1)
    index_backlog(migrated_engine, world.storage, ScanReader(), None, world.company, capped)
    assert _library_row(migrated_engine, first) is not None
    assert _library_row(migrated_engine, second) is None  # waits for tomorrow's cap
    assert _calls(migrated_engine) == 1


def _failing(monkeypatch: pytest.MonkeyPatch, exc: Exception) -> list[int]:
    seen: list[int] = []

    def fail(*args: object, **kwargs: object) -> str:
        seen.append(1)
        raise exc

    monkeypatch.setattr(brixx_library, "ocr_scan", fail)
    return seen


@pytest.mark.parametrize("exc", [AgentFailedError("doc_ocr: 402"), TimeoutError("read timed out")])
def test_a_failing_vision_call_stops_the_run_and_gives_up_after_three_tries(
    migrated_engine: Engine, world: World, test_settings: Settings, monkeypatch: pytest.MonkeyPatch, exc: Exception
) -> None:
    index_backlog(
        migrated_engine, world.storage, Reader(), None, world.company, world.settings
    )  # the text documents first
    one = _scan(migrated_engine, world, 27, "Huurovereenkomst scan", b"SCAN Allonge een.")
    two = _scan(migrated_engine, world, 28, "Huurovereenkomst scan 2", b"SCAN Allonge twee.")
    seen = _failing(monkeypatch, exc)

    def run() -> int:
        return index_backlog(migrated_engine, world.storage, ScanReader(), None, world.company, world.settings)

    assert run() == 0
    assert len(seen) == 1  # the run stops at the first failure: an outage costs one call per sync
    assert _library_row(migrated_engine, one) is None  # not given up yet: a later sync tries again
    for _ in range(2 * brixx_library.MAX_OCR_ATTEMPTS - 1):
        run()
    assert len(seen) == 2 * brixx_library.MAX_OCR_ATTEMPTS
    for row in (one, two):
        doc = _library_row(migrated_engine, row)
        assert doc is not None
        assert (doc.status, doc.error) == (DocumentStatus.skipped, "vision failed")
    run()
    assert len(seen) == 2 * brixx_library.MAX_OCR_ATTEMPTS  # given up: never sent again


def test_a_version_that_failed_vision_goes_to_the_back_of_the_backlog(
    migrated_engine: Engine, world: World, test_settings: Settings
) -> None:
    index_backlog(migrated_engine, world.storage, Reader(), None, world.company, world.settings)
    failed = _scan(migrated_engine, world, 27, "Huurovereenkomst scan", b"SCAN Allonge een.")
    later = _scan(migrated_engine, world, 28, "Huurovereenkomst scan 2", b"SCAN Allonge twee.")
    with Session(migrated_engine) as s, s.begin():
        s.get_one(BrixxDocument, failed).ocr_attempts = 1
    assert unindexed(migrated_engine, world.company) == [later, failed]
