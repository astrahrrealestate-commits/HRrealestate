"""#9 wiring: `documents.file_document` workflow. A transient failure sending the review card is retried (N9)."""

from collections.abc import Callable, Iterator
from typing import Any, cast
from uuid import UUID

import pytest
from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from app.core.errors import EstateOSError
from app.db.models import DocumentChunk, DocumentLink
from app.ingestion.process import IngestDeps
from app.storage.drive import MemoryDrive
from app.storage.extract import FakeExtractor
from app.storage.memory import MemoryStorage
from app.workflows import documents
from app.workflows.deps import set_deps, set_drive, set_extractor
from tests.integration.test_documents import _attachment

pytestmark = pytest.mark.integration


class ProviderBlipError(EstateOSError):
    retryable = True


@pytest.fixture
def storage(dbos_runtime: None, migrated_engine: Engine) -> Iterator[MemoryStorage]:
    store = MemoryStorage()
    set_deps(IngestDeps(migrated_engine, store, cast(Any, None), lambda a: None, lambda p: None, "t"))  # type: ignore[arg-type, return-value]
    set_drive(MemoryDrive())
    yield store
    set_drive(None)
    set_deps(None)


def _flaky(failures: int) -> tuple[list[str], Callable[..., bool]]:
    calls: list[str] = []

    def send(company_id: str, key: str, build: object) -> bool:
        calls.append(key)
        if len(calls) <= failures:
            raise ProviderBlipError("whatsapp 503")
        return True

    return calls, send


def test_review_card_survives_a_transient_send_failure(
    storage: MemoryStorage, migrated_engine: Engine, committed_company: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    company_id: UUID = committed_company.id
    att = _attachment(migrated_engine, company_id, storage, "IMG_2041.jpg", "image/jpeg", b"\xff\xd8" + b"j" * 40_000)
    calls, send = _flaky(failures=1)
    monkeypatch.setattr(documents, "send_owner_message", send)
    assert documents.file_document_wf(str(company_id), str(att), None) == "review"
    assert calls == [f"docreview:{att}", f"docreview:{att}"]  # retried once, same idempotency key


def test_workflow_reads_files_and_links_a_document(
    storage: MemoryStorage, migrated_engine: Engine, committed_company: Any
) -> None:
    company_id: UUID = committed_company.id
    text = b"Huurovereenkomst\nHuurder: Anna de Vries\nWaarborgsom: twee maanden huur"
    att = _attachment(migrated_engine, company_id, storage, "scan.pdf", "application/pdf", text)
    set_extractor(FakeExtractor())
    try:
        assert documents.file_document_wf(str(company_id), str(att), None) == "filed"
    finally:
        set_extractor(None)
    with Session(migrated_engine) as session:
        chunks = session.scalars(select(DocumentChunk.text).where(DocumentChunk.company_id == company_id)).all()
        links = session.scalars(select(DocumentLink.kind).where(DocumentLink.company_id == company_id)).all()
    assert len(chunks) == 1
    assert "waarborgsom" in chunks[0].lower()
    with Session(migrated_engine) as session:  # the workflow's last step embedded them
        assert (
            session.scalars(select(DocumentChunk.embedding).where(DocumentChunk.company_id == company_id)).first()
            is not None
        )
    assert [k.value for k in links] == ["person"]  # the sender; no case or directory match in this fixture


def test_reorg_workflow_applies_an_approved_plan_and_a_repeat_is_harmless(
    storage: MemoryStorage, migrated_engine: Engine, committed_company: Any
) -> None:
    from datetime import date

    from app.db.enums import PersonKind
    from app.db.models import DocumentRow, Person, Unit
    from app.pipeline.drive_reorg import build_plan, decide_plan
    from app.workflows import drive_reorg
    from app.workflows.deps import get_drive

    company_id: UUID = committed_company.id
    att = _attachment(migrated_engine, company_id, storage, "factuur.pdf", "application/pdf", b"%PDF" + b"x" * 5000)
    assert documents.file_document_wf(str(company_id), str(att), None) == "filed"
    with Session(migrated_engine) as s, s.begin():
        unit = Unit(company_id=company_id, label="Kerkstraat 12-2", valid_from=date(2025, 1, 1))
        s.add(unit)
        s.flush()
        doc = s.scalars(select(DocumentRow).where(DocumentRow.attachment_id == att)).one()
        s.add(Person(company_id=company_id, kind=PersonKind.tenant, display_name="Anna", valid_from=date(2025, 1, 1)))
        from app.db.enums import DocLinkKind
        from app.db.models import DocumentLink

        s.add(DocumentLink(company_id=company_id, document_id=doc.id, kind=DocLinkKind.unit, ref_id=unit.id,
                           method="owner", score=1.0))  # fmt: skip
    plan = build_plan(migrated_engine, company_id, "owner")
    assert plan is not None
    decide_plan(migrated_engine, company_id, plan, True, None)
    assert drive_reorg.reorg_plan_wf(str(company_id), str(plan)) == {"moved": 1}
    assert drive_reorg.reorg_plan_wf(str(company_id), str(plan)) == {}
    drive = get_drive()
    assert isinstance(drive, MemoryDrive)
    assert [drive.path_of(f) for f in drive.files] == [("EstateOS", "Kerkstraat 12-2", "Invoices", "2026")]


def test_an_embedding_outage_does_not_fail_the_filing_workflow(
    storage: MemoryStorage, migrated_engine: Engine, committed_company: Any
) -> None:
    from app.llm.embeddings import HashingEmbedder
    from app.workflows.deps import set_embedder

    class Down(HashingEmbedder):
        def embed_documents(self, texts):  # type: ignore[no-untyped-def]
            raise ValueError("401 invalid api key")

    company_id: UUID = committed_company.id
    text = b"Huurovereenkomst\nHuurder: Anna de Vries\nWaarborgsom: twee maanden huur"
    att = _attachment(migrated_engine, company_id, storage, "scan.pdf", "application/pdf", text)
    set_extractor(FakeExtractor())
    set_embedder(Down())
    try:
        assert documents.file_document_wf(str(company_id), str(att), None) == "filed"
    finally:
        set_embedder(None)
        set_extractor(None)
    with Session(migrated_engine) as session:  # filed and indexed by words; the vectors wait for the backfill
        assert (
            session.scalars(select(DocumentChunk.embedding).where(DocumentChunk.company_id == company_id)).first()
            is None
        )
