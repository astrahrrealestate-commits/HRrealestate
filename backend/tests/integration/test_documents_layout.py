"""Layout v2 end to end: documents land in their unit's folder with the tenant's name and searchable Drive metadata."""

from datetime import UTC, date, datetime
from uuid import UUID

import pytest
from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from app.contracts import CaseState, Category, Channel, Direction, Urgency
from app.core.ids import new_id
from app.core.settings import Settings
from app.db.enums import DocumentStatus, LinkMethod, PersonKind
from app.db.models import AttachmentRow, Case, CaseLink, Company, DocumentRow, MessageRow, Person, RawEvent, Unit
from app.pipeline.documents import file_document
from app.storage.drive import MemoryDrive
from app.storage.extract import FakeExtractor
from app.storage.memory import MemoryStorage

pytestmark = pytest.mark.integration
SENT = datetime(2026, 10, 6, 23, 30, tzinfo=UTC)
LEASE = b"Huurovereenkomst\nHuurder: Anna de Vries\nAdres: Kerkstraat 12-2\nWaarborgsom: twee maanden huur"


@pytest.fixture
def settings(test_settings: Settings) -> Settings:
    return test_settings.model_copy(update={"llm_model": "fake"})


def _world(
    engine: Engine, cid: UUID, storage: MemoryStorage, *, case_unit: bool, label: str = "Kerkstraat 12-2"
) -> UUID:
    """A message from the contractor Jan with one PDF; optionally in a case whose unit is `label`."""
    storage.put("k", LEASE, "application/pdf")
    with Session(engine) as s, s.begin():
        since = date(2025, 1, 1)
        jan = Person(company_id=cid, kind=PersonKind.contractor, display_name="Jan Bakker", valid_from=since)
        anna = Person(company_id=cid, kind=PersonKind.tenant, display_name="Anna de Vries", valid_from=since)
        unit = Unit(company_id=cid, label=label, address=f"{label}, Amsterdam", valid_from=since)
        s.add_all([jan, anna, unit])
        s.flush()
        raw = RawEvent(company_id=cid, provider=Channel.gmail, provider_msg_id=str(new_id()), payload={})
        s.add(raw)
        s.flush()
        msg = MessageRow(company_id=cid, raw_event_id=raw.id, channel=Channel.gmail,
                         provider_msg_id=raw.provider_msg_id, thread_ref="t", sender_identity="j@example.test",
                         direction=Direction.inbound, sent_at=SENT, text="bijlage", meta={},
                         person_id=jan.id)  # fmt: skip
        s.add(msg)
        s.flush()
        if case_unit:
            case = Case(company_id=cid, unit_id=unit.id, primary_person_id=anna.id, state=CaseState.open,
                        category=Category.other, urgency=Urgency.normal)  # fmt: skip
            s.add(case)
            s.flush()
            s.add(CaseLink(company_id=cid, case_id=case.id, message_id=msg.id, method=LinkMethod.thread))
        att = AttachmentRow(company_id=cid, message_id=msg.id, s3_key="k", mime_type="application/pdf",
                            filename="scan.pdf", size_bytes=len(LEASE), sha256="0" * 64)  # fmt: skip
        s.add(att)
        s.flush()
        return att.id


def _file(engine: Engine, settings: Settings, storage: MemoryStorage, drive: MemoryDrive, cid: UUID, att: UUID) -> None:
    status = file_document(engine, settings, storage, drive, cid, att, extractor=FakeExtractor())
    assert status is DocumentStatus.filed


def _row(engine: Engine, att: UUID) -> DocumentRow:
    with Session(engine) as s:
        return s.scalars(select(DocumentRow).where(DocumentRow.attachment_id == att)).one()


def test_the_case_unit_gives_the_folder_and_the_named_tenant_gives_the_file_name(
    migrated_engine: Engine, settings: Settings, committed_company: Company
) -> None:
    cid, storage, drive = committed_company.id, MemoryStorage(), MemoryDrive()
    att = _world(migrated_engine, cid, storage, case_unit=True)
    _file(migrated_engine, settings, storage, drive, cid, att)
    row = _row(migrated_engine, att)
    assert row.drive_folder == "EstateOS/Kerkstraat 12-2/Leases/2026"
    assert row.file_name == "2026-10-07_lease_anna-de-vries_lease-agreement.pdf"
    assert row.drive_file_id is not None
    assert drive.path_of(row.drive_file_id) == ("EstateOS", "Kerkstraat 12-2", "Leases", "2026")
    props = drive.properties[row.drive_file_id]
    assert (props["doc_type"], props["unit"], props["party"], props["date"]) == (
        "lease", "Kerkstraat 12-2", "anna-de-vries", "2026-10-07"
    )  # fmt: skip
    assert drive.description[row.drive_file_id] == row.summary


def test_the_address_in_the_document_places_it_when_there_is_no_case(
    migrated_engine: Engine, settings: Settings, committed_company: Company
) -> None:
    cid, storage, drive = committed_company.id, MemoryStorage(), MemoryDrive()
    att = _world(migrated_engine, cid, storage, case_unit=False)
    _file(migrated_engine, settings, storage, drive, cid, att)
    assert _row(migrated_engine, att).drive_folder == "EstateOS/Kerkstraat 12-2/Leases/2026"


def test_a_path_separator_in_a_unit_label_cannot_split_the_folder(
    migrated_engine: Engine, settings: Settings, committed_company: Company
) -> None:
    cid, storage, drive = committed_company.id, MemoryStorage(), MemoryDrive()
    att = _world(migrated_engine, cid, storage, case_unit=True, label="Kerkstraat 12/2")
    _file(migrated_engine, settings, storage, drive, cid, att)
    folder = _row(migrated_engine, att).drive_folder
    assert folder == "EstateOS/Kerkstraat 12 2/Leases/2026"
    assert folder is not None
    assert len(folder.split("/")) == 4


def test_without_any_unit_evidence_it_is_unsorted(
    migrated_engine: Engine, settings: Settings, committed_company: Company
) -> None:
    cid, storage, drive = committed_company.id, MemoryStorage(), MemoryDrive()
    att = _world(migrated_engine, cid, storage, case_unit=False, label="Zeestraat 99")  # the address does not match
    _file(migrated_engine, settings, storage, drive, cid, att)
    row = _row(migrated_engine, att)
    assert row.drive_folder == "EstateOS/_Unsorted/Leases/2026"
    assert row.file_name == "2026-10-07_lease_anna-de-vries_lease-agreement.pdf"  # the tenant the text names
    assert row.drive_file_id is not None
    assert "unit" not in drive.properties[row.drive_file_id]
