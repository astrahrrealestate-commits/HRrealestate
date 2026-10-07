"""#9 document filing against Postgres: classify → file / review / skip, idempotent, owner override, tenant-scoped."""

import hashlib
from datetime import UTC, datetime
from uuid import UUID

import pytest
from sqlalchemy import Engine, func, select
from sqlalchemy.orm import Session

from app.contracts import Channel, Direction, DocType
from app.core.errors import NotFoundError
from app.core.ids import new_id
from app.core.settings import Settings
from app.db.enums import DocumentStatus, PersonKind
from app.db.models import AttachmentRow, Company, DocumentRow, MessageRow, ModelCall, Person, RawEvent
from app.llm import fakes
from app.pipeline.documents import file_document, skip_document
from app.storage.drive import DriveApiError, MemoryDrive
from app.storage.memory import MemoryStorage

pytestmark = pytest.mark.integration
SENT = datetime(2026, 10, 6, 23, 30, tzinfo=UTC)  # 7 Oct in Amsterdam


@pytest.fixture
def fake_settings(test_settings: Settings) -> Settings:
    return test_settings.model_copy(update={"llm_model": "fake"})


@pytest.fixture
def storage() -> MemoryStorage:
    return MemoryStorage()


def _attachment(engine: Engine, company_id: UUID, storage: MemoryStorage, name: str | None, mime: str,
                data: bytes, text: str | None = None) -> UUID:  # fmt: skip
    sha = hashlib.sha256(data).hexdigest()
    key = f"media/{company_id}/{sha[:2]}/{sha}"
    storage.put(key, data, mime)
    with Session(engine) as session, session.begin():
        person = Person(
            company_id=company_id, kind=PersonKind.contractor, display_name="Jan de Loodgieter", valid_from=SENT.date()
        )
        raw = RawEvent(company_id=company_id, provider=Channel.gmail, provider_msg_id=str(new_id()), payload={})
        session.add_all([person, raw])
        session.flush()
        msg = MessageRow(company_id=company_id, raw_event_id=raw.id, channel=Channel.gmail,
                         provider_msg_id=raw.provider_msg_id, thread_ref="t", sender_identity="jan@example.test",
                         direction=Direction.inbound, sent_at=SENT, text="zie bijlage", meta={},
                         person_id=person.id)  # fmt: skip
        session.add(msg)
        session.flush()
        att = AttachmentRow(company_id=company_id, message_id=msg.id, s3_key=key, mime_type=mime, filename=name,
                            size_bytes=len(data), sha256=sha, extracted_text=text)  # fmt: skip
        session.add(att)
        session.flush()
        return att.id


def _doc(engine: Engine, attachment_id: UUID) -> DocumentRow:
    with Session(engine) as session:
        row = session.scalar(select(DocumentRow).where(DocumentRow.attachment_id == attachment_id))
        assert row is not None
        return row


@pytest.fixture
def company_id(committed_company: Company) -> UUID:
    return committed_company.id


PDF = b"%PDF-1.4 " + b"x" * 5000


def test_invoice_is_filed_once(migrated_engine: Engine, fake_settings: Settings, storage: MemoryStorage,
                               company_id: UUID) -> None:  # fmt: skip
    att = _attachment(migrated_engine, company_id, storage, "factuur_2026-17.pdf", "application/pdf", PDF)
    drive = MemoryDrive()
    assert file_document(migrated_engine, fake_settings, storage, drive, company_id, att) is DocumentStatus.filed
    assert file_document(migrated_engine, fake_settings, storage, drive, company_id, att) is DocumentStatus.filed
    row = _doc(migrated_engine, att)
    assert row.file_name == "2026-10-07_invoice_jan-de-loodgieter_invoice.pdf"
    assert (row.doc_type, row.drive_folder) == ("invoice", "EstateOS/invoice/2026")
    assert row.drive_file_id in drive.files
    assert len(drive.files) == 1
    with Session(migrated_engine) as session:
        assert session.scalar(select(func.count()).select_from(ModelCall).where(ModelCall.id == row.model_call_id)) == 1


def test_low_confidence_photo_waits_for_owner_then_files(migrated_engine: Engine, fake_settings: Settings,
                                                         storage: MemoryStorage, company_id: UUID) -> None:  # fmt: skip
    att = _attachment(migrated_engine, company_id, storage, "IMG_2041.jpg", "image/jpeg", b"\xff\xd8" + b"j" * 40_000)
    drive = MemoryDrive()
    assert file_document(migrated_engine, fake_settings, storage, drive, company_id, att) is DocumentStatus.review
    assert file_document(migrated_engine, fake_settings, storage, drive, company_id, att) is DocumentStatus.review
    assert drive.files == {}
    status = file_document(migrated_engine, fake_settings, storage, drive, company_id, att,
                           owner_doc_type=DocType.photo)  # fmt: skip
    assert status is DocumentStatus.filed
    row = _doc(migrated_engine, att)
    assert (row.doc_type, row.confidence, row.file_name.endswith(".jpg")) == ("photo", 1.0, True)


def test_tiny_logo_is_skipped_without_a_model_call(migrated_engine: Engine, fake_settings: Settings,
                                                   storage: MemoryStorage, company_id: UUID) -> None:  # fmt: skip
    att = _attachment(migrated_engine, company_id, storage, "logo.png", "image/png", b"\x89PNG" + b"p" * 900)
    status = file_document(migrated_engine, fake_settings, storage, MemoryDrive(), company_id, att)
    assert status is DocumentStatus.skipped
    assert _doc(migrated_engine, att).model_call_id is None


def test_model_failure_marks_failed(migrated_engine: Engine, fake_settings: Settings, storage: MemoryStorage,
                                    company_id: UUID, monkeypatch: pytest.MonkeyPatch) -> None:  # fmt: skip
    monkeypatch.setattr(fakes, "_fake_doc_classifier", lambda prompt: {"doc_type": "nonsense"})
    att = _attachment(migrated_engine, company_id, storage, "a.pdf", "application/pdf", PDF)
    status = file_document(migrated_engine, fake_settings, storage, MemoryDrive(), company_id, att)
    assert status is DocumentStatus.failed
    row = _doc(migrated_engine, att)
    assert row.error
    assert row.drive_file_id is None


def test_other_company_cannot_file_it(migrated_engine: Engine, fake_settings: Settings, storage: MemoryStorage,
                                      company_id: UUID) -> None:  # fmt: skip
    att = _attachment(migrated_engine, company_id, storage, "factuur.pdf", "application/pdf", PDF)
    with pytest.raises(NotFoundError):
        file_document(migrated_engine, fake_settings, storage, MemoryDrive(), new_id(), att)


def test_classifier_never_sees_file_contents(
    migrated_engine: Engine, fake_settings: Settings, storage: MemoryStorage, company_id: UUID
) -> None:
    """User decision: metadata only. Extracted text and file bytes stay out of the model prompt."""
    att = _attachment(
        migrated_engine, company_id, storage, "scan.pdf", "application/pdf", b"%PDF BYTES-SECRET", text="TEXT-SECRET"
    )
    file_document(migrated_engine, fake_settings, storage, MemoryDrive(), company_id, att)
    with Session(migrated_engine) as session:
        call = session.get(ModelCall, _doc(migrated_engine, att).model_call_id)
        assert call is not None
        prompt = call.input["prompt"]
    assert "zie bijlage" in prompt
    assert "scan.pdf" in prompt
    assert "TEXT-SECRET" not in prompt
    assert "BYTES-SECRET" not in prompt


def _calls(engine: Engine, company_id: UUID) -> int:
    with Session(engine) as session:
        query = select(func.count()).select_from(ModelCall).where(ModelCall.company_id == company_id)
        return int(session.scalar(query) or 0)


class FlakyDrive(MemoryDrive):
    """Fails the first upload with a retryable error, as a 503 or a crash mid-upload would."""

    def __init__(self) -> None:
        super().__init__()
        self.failures = 1

    def upload(self, file_id: str, folder_id: str, name: str, mime_type: str, content: bytes,
               attachment_id: UUID) -> str:  # fmt: skip
        if self.failures:
            self.failures -= 1
            raise DriveApiError("drive upload failed (503)", status=503, retryable=True)
        return super().upload(file_id, folder_id, name, mime_type, content, attachment_id)


def test_retry_after_failed_upload_reuses_plan_without_a_second_model_call(
    migrated_engine: Engine, fake_settings: Settings, storage: MemoryStorage, company_id: UUID
) -> None:
    att = _attachment(migrated_engine, company_id, storage, "factuur.pdf", "application/pdf", PDF)
    drive = FlakyDrive()
    with pytest.raises(DriveApiError):
        file_document(migrated_engine, fake_settings, storage, drive, company_id, att)
    pending = _doc(migrated_engine, att)
    assert pending.status is DocumentStatus.pending
    assert pending.drive_file_id is not None
    calls = _calls(migrated_engine, company_id)
    assert file_document(migrated_engine, fake_settings, storage, drive, company_id, att) is DocumentStatus.filed
    assert _calls(migrated_engine, company_id) == calls  # the plan was reused, not re-classified
    assert list(drive.files) == [pending.drive_file_id]  # uploaded with the id reserved before the first try


def test_file_already_in_drive_is_found_not_uploaded_again(
    migrated_engine: Engine, fake_settings: Settings, storage: MemoryStorage, company_id: UUID
) -> None:
    att = _attachment(migrated_engine, company_id, storage, "factuur.pdf", "application/pdf", PDF)
    drive = MemoryDrive()
    earlier = drive.upload("earlier-copy", drive.ensure_folder(("EstateOS",)), "x.pdf", "application/pdf", PDF, att)
    assert file_document(migrated_engine, fake_settings, storage, drive, company_id, att) is DocumentStatus.filed
    assert len(drive.files) == 1
    assert _doc(migrated_engine, att).drive_file_id == earlier


def test_owner_choice_files_exactly_once_even_when_repeated(
    migrated_engine: Engine, fake_settings: Settings, storage: MemoryStorage, company_id: UUID
) -> None:
    att = _attachment(migrated_engine, company_id, storage, "scan.pdf", "application/pdf", PDF)
    drive = MemoryDrive()
    assert file_document(migrated_engine, fake_settings, storage, drive, company_id, att) is DocumentStatus.review
    for _ in range(2):  # a double tap on the review card
        status = file_document(
            migrated_engine, fake_settings, storage, drive, company_id, att, owner_doc_type=DocType.invoice
        )
        assert status is DocumentStatus.filed
    assert len(drive.files) == 1
    assert _doc(migrated_engine, att).doc_type == "invoice"


def test_owner_skip(migrated_engine: Engine, fake_settings: Settings, storage: MemoryStorage, company_id: UUID) -> None:
    att = _attachment(migrated_engine, company_id, storage, "scan.pdf", "application/pdf", PDF)
    file_document(migrated_engine, fake_settings, storage, MemoryDrive(), company_id, att)
    assert skip_document(migrated_engine, company_id, att) is DocumentStatus.skipped
    assert (
        file_document(migrated_engine, fake_settings, storage, MemoryDrive(), company_id, att) is DocumentStatus.skipped
    )
    with pytest.raises(NotFoundError):
        skip_document(migrated_engine, new_id(), att)


def test_unknown_sender_never_lands_in_the_file_name(
    migrated_engine: Engine, fake_settings: Settings, storage: MemoryStorage, company_id: UUID
) -> None:
    att = _attachment(migrated_engine, company_id, storage, "factuur.pdf", "application/pdf", PDF)
    with Session(migrated_engine) as session, session.begin():
        msg_id = session.scalar(select(AttachmentRow.message_id).where(AttachmentRow.id == att))
        session.get(MessageRow, msg_id).person_id = None  # type: ignore[union-attr]
    file_document(migrated_engine, fake_settings, storage, MemoryDrive(), company_id, att)
    name = _doc(migrated_engine, att).file_name
    assert "_unknown_" in name
    assert "jan" not in name
