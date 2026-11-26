"""Attachments are read before the draft (M13 T8 part, lane A): their text is in the dossier of the first proposal."""

from uuid import UUID

import pytest
from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from app.core.settings import Settings
from app.db.enums import ExtractionStatus
from app.db.models import AttachmentRow, Company
from app.llm.embeddings import HashingEmbedder
from app.pipeline.dossier import build_dossier
from app.pipeline.draft_reading import read_attachments
from app.storage.extract import Extraction
from app.storage.memory import MemoryStorage
from tests.integration.conversation_support import add_case, add_mail, add_person

pytestmark = pytest.mark.integration
ANOUK = "anouk@example.test"


class Reader:
    """Reads the stored bytes as text; counts the calls."""

    def __init__(self) -> None:
        self.calls = 0

    def extract(self, data: bytes, mime_type: str, filename: str | None) -> Extraction:
        self.calls += 1
        return Extraction(ExtractionStatus.done, data.decode(), 1, "fake")


def _file(engine: Engine, cid: UUID, mid: UUID, storage: MemoryStorage, name: str, data: bytes, mime: str) -> UUID:
    key = f"att/{name}"
    storage.put(key, data, mime)
    with Session(engine) as s, s.begin():
        row = AttachmentRow(company_id=cid, message_id=mid, s3_key=key, mime_type=mime, filename=name,
                            size_bytes=max(len(data), 30_000), sha256="0" * 64)  # fmt: skip
        s.add(row)
        s.flush()
        return row.id


def _mail(engine: Engine, cid: UUID) -> UUID:
    anouk = add_person(engine, cid, "Anouk", ANOUK)
    return add_mail(engine, cid, "Zie bijlage", sender=ANOUK, person_id=anouk, case_id=add_case(engine, cid, anouk))


def test_attachment_text_is_stored_before_the_proposer_runs(
    migrated_engine: Engine, committed_company: Company, test_settings: Settings
) -> None:
    cid, storage, reader = committed_company.id, MemoryStorage(), Reader()
    mid = _mail(migrated_engine, cid)
    _file(migrated_engine, cid, mid, storage, "offerte.pdf", b"Stucwerk EUR 4.800", "application/pdf")
    assert read_attachments(migrated_engine, test_settings, storage, reader, mid) == 1
    with Session(migrated_engine) as s:
        dossier = build_dossier(s, cid, mid, HashingEmbedder())
    assert [a.text for a in dossier.attachments] == ["Stucwerk EUR 4.800"]


def test_reading_twice_reads_once(migrated_engine: Engine, committed_company: Company, test_settings: Settings) -> None:
    cid, storage, reader = committed_company.id, MemoryStorage(), Reader()
    mid = _mail(migrated_engine, cid)
    _file(migrated_engine, cid, mid, storage, "offerte.pdf", b"EUR 4.800", "application/pdf")
    read_attachments(migrated_engine, test_settings, storage, reader, mid)
    read_attachments(migrated_engine, test_settings, storage, reader, mid)
    assert reader.calls == 1


def test_identity_documents_and_tiny_images_are_never_read(
    migrated_engine: Engine, committed_company: Company, test_settings: Settings
) -> None:
    cid, storage, reader = committed_company.id, MemoryStorage(), Reader()
    mid = _mail(migrated_engine, cid)
    _file(migrated_engine, cid, mid, storage, "paspoort_anouk.pdf", b"NL ID 123", "application/pdf")
    with Session(migrated_engine) as s, s.begin():
        logo = AttachmentRow(company_id=cid, message_id=mid, s3_key="att/logo.png", mime_type="image/png",
                             filename="logo.png", size_bytes=900, sha256="1" * 64)  # fmt: skip
        s.add(logo)
    assert read_attachments(migrated_engine, test_settings, storage, reader, mid) == 0
    assert reader.calls == 0
    with Session(migrated_engine) as s:
        statuses = s.scalars(select(AttachmentRow.extraction_status).where(AttachmentRow.message_id == mid)).all()
    assert set(statuses) == {None}


def test_an_unreadable_file_does_not_stop_the_others(
    migrated_engine: Engine, committed_company: Company, test_settings: Settings
) -> None:
    cid, reader = committed_company.id, Reader()
    storage = MemoryStorage()
    mid = _mail(migrated_engine, cid)
    with Session(migrated_engine) as s, s.begin():
        s.add(AttachmentRow(company_id=cid, message_id=mid, s3_key="att/missing.pdf", mime_type="application/pdf",
                            filename="weg.pdf", size_bytes=30_000, sha256="2" * 64))  # fmt: skip
    _file(migrated_engine, cid, mid, storage, "offerte.pdf", b"EUR 4.800", "application/pdf")
    assert read_attachments(migrated_engine, test_settings, storage, reader, mid) == 1


def test_prepare_for_draft_reads_the_quote_and_the_dossier_shows_its_review(
    migrated_engine: Engine, committed_company: Company, test_settings: Settings
) -> None:
    from app.ingestion.process import IngestDeps
    from app.workflows import deps
    from app.workflows.prepare import prepare_for_draft
    from tests.integration.finance_support import message, seed_case

    cid, storage, reader = committed_company.id, MemoryStorage(), Reader()
    with Session(migrated_engine) as s:
        seeded = seed_case(s, cid)
        mid = message(s, cid, seeded.case_id, "Offerte in de bijlage.", person_id=seeded.vendor_id)
        s.commit()
    _file(migrated_engine, cid, mid, storage, "offerte.pdf", "Offerte\nCv ketel onderhoud € 131,00 excl. BTW".encode(),
          "application/pdf")  # fmt: skip
    deps.set_deps(IngestDeps(engine=migrated_engine, storage=storage, enqueuer=None, gmail_mailbox=lambda a: None,  # type: ignore[arg-type]
                             whatsapp_media=lambda p: None, gmail_topic="t"))  # type: ignore[arg-type]  # fmt: skip
    deps.set_extractor(reader)
    try:
        prepare_for_draft(migrated_engine, test_settings, mid, research=False)
    finally:
        deps.set_deps(None)
        deps.set_extractor(None)
    with Session(migrated_engine) as s:
        dossier = build_dossier(s, cid, mid, HashingEmbedder())
    assert dossier.attachments
    assert dossier.quote is not None
    assert "131" in dossier.quote
