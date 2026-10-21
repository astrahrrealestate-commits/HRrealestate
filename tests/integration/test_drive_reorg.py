"""Drive reorganisation: propose moves, owner decides, apply once; stale, missing and flaky files are handled."""

from dataclasses import dataclass
from datetime import UTC, date, datetime
from uuid import UUID

import pytest
from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from app.contracts import Channel, Direction
from app.core.errors import NotFoundError
from app.core.ids import new_id
from app.db.enums import DocLinkKind, DocumentStatus, PersonKind, ReorgItemStatus, ReorgPlanStatus
from app.db.models import (
    AttachmentRow,
    Company,
    DocumentLink,
    DocumentRow,
    DriveReorgItem,
    DriveReorgPlan,
    MessageRow,
    Person,
    RawEvent,
    Unit,
)
from app.pipeline.drive_reorg import apply_plan, build_plan, decide_plan
from app.storage.drive import DriveApiError, MemoryDrive

pytestmark = pytest.mark.integration
OLD_FOLDER = "EstateOS/lease/2026"
OLD_NAME = "2026-10-07_lease_jan-bakker_huurovereenkomst.pdf"
NEW_FOLDER = "EstateOS/Kerkstraat 12-2/Leases/2026"
NEW_NAME = "2026-10-07_lease_anna-de-vries_huurovereenkomst.pdf"


@dataclass
class World:
    company_id: UUID
    anna: UUID
    unit: UUID
    drive: MemoryDrive
    engine: Engine


@pytest.fixture
def w(migrated_engine: Engine, committed_company: Company) -> World:
    cid = committed_company.id
    with Session(migrated_engine) as s, s.begin():
        since = date(2025, 1, 1)
        anna = Person(company_id=cid, kind=PersonKind.tenant, display_name="Anna de Vries", valid_from=since)
        unit = Unit(company_id=cid, label="Kerkstraat 12-2", valid_from=since)
        s.add_all([anna, unit])
        s.flush()
        return World(cid, anna.id, unit.id, MemoryDrive(), migrated_engine)


def _filed(w: World, *, name: str = OLD_NAME, folder: str = OLD_FOLDER, linked: bool = True) -> UUID:
    """A document filed under layout v1 whose unit and tenant are known (links), plus its file in the fake Drive."""
    with Session(w.engine) as s, s.begin():
        raw = RawEvent(company_id=w.company_id, provider=Channel.gmail, provider_msg_id=str(new_id()), payload={})
        s.add(raw)
        s.flush()
        msg = MessageRow(company_id=w.company_id, raw_event_id=raw.id, channel=Channel.gmail,
                         provider_msg_id=raw.provider_msg_id, thread_ref="t", sender_identity="j@example.test",
                         direction=Direction.inbound, sent_at=datetime(2026, 10, 6, tzinfo=UTC), text="t",
                         meta={})  # fmt: skip
        s.add(msg)
        s.flush()
        att = AttachmentRow(company_id=w.company_id, message_id=msg.id, s3_key="k", mime_type="application/pdf",
                            filename="x.pdf", size_bytes=9, sha256="0" * 64)  # fmt: skip
        s.add(att)
        s.flush()
        file_id = w.drive.new_file_id()
        w.drive.upload(
            file_id, w.drive.ensure_folder(tuple(folder.split("/"))), name, "application/pdf", b"%PDF", att.id
        )
        doc = DocumentRow(company_id=w.company_id, attachment_id=att.id, doc_type="lease", title="Huurovereenkomst",
                          file_name=name, confidence=0.9, status=DocumentStatus.filed, drive_file_id=file_id,
                          drive_folder=folder)  # fmt: skip
        s.add(doc)
        s.flush()
        if linked:
            for kind, ref in ((DocLinkKind.unit, w.unit), (DocLinkKind.person, w.anna)):
                s.add(DocumentLink(company_id=w.company_id, document_id=doc.id, kind=kind, ref_id=ref, method="fuzzy",
                                   score=0.9))  # fmt: skip
        return doc.id


def _doc(w: World, doc_id: UUID) -> DocumentRow:
    with Session(w.engine) as s:
        return s.scalars(select(DocumentRow).where(DocumentRow.id == doc_id)).one()


def _items(w: World, plan_id: UUID) -> dict[UUID, DriveReorgItem]:
    with Session(w.engine) as s:
        return {i.document_id: i for i in s.scalars(select(DriveReorgItem).where(DriveReorgItem.plan_id == plan_id))}


def _plan_status(w: World, plan_id: UUID) -> ReorgPlanStatus:
    with Session(w.engine) as s:
        return s.scalars(select(DriveReorgPlan.status).where(DriveReorgPlan.id == plan_id)).one()


def test_a_plan_proposes_the_move_and_moves_nothing(w: World) -> None:
    doc = _filed(w)
    plan = build_plan(w.engine, w.company_id, "owner")
    assert plan is not None
    item = _items(w, plan)[doc]
    assert (item.from_folder, item.to_folder) == (OLD_FOLDER, NEW_FOLDER)
    assert (item.from_name, item.to_name) == (OLD_NAME, NEW_NAME)
    assert item.status is ReorgItemStatus.proposed
    assert _plan_status(w, plan) is ReorgPlanStatus.proposed
    assert _doc(w, doc).drive_folder == OLD_FOLDER
    assert w.drive.path_of(_doc(w, doc).drive_file_id or "") == tuple(OLD_FOLDER.split("/"))


def test_building_again_does_not_plan_the_same_move_twice(w: World) -> None:
    _filed(w)
    assert build_plan(w.engine, w.company_id, "owner") is not None
    assert build_plan(w.engine, w.company_id, "owner") is None


def test_a_document_already_where_it_belongs_needs_no_move(w: World) -> None:
    _filed(w, name=NEW_NAME, folder=NEW_FOLDER)
    assert build_plan(w.engine, w.company_id, "owner") is None


def test_without_a_unit_it_belongs_in_unsorted(w: World) -> None:
    doc = _filed(w, linked=False)
    plan = build_plan(w.engine, w.company_id, "owner")
    assert plan is not None
    item = _items(w, plan)[doc]
    assert (item.to_folder, item.to_name) == ("EstateOS/_Unsorted/Leases/2026", OLD_NAME)


def test_approve_and_apply_moves_the_file_once(w: World) -> None:
    doc = _filed(w)
    plan = build_plan(w.engine, w.company_id, "owner")
    assert plan is not None
    assert decide_plan(w.engine, w.company_id, plan, True, None) is ReorgPlanStatus.approved
    assert apply_plan(w.engine, w.drive, w.company_id, plan) == {"moved": 1}
    row = _doc(w, doc)
    assert (row.drive_folder, row.file_name) == (NEW_FOLDER, NEW_NAME)
    assert row.drive_file_id is not None
    assert w.drive.path_of(row.drive_file_id) == tuple(NEW_FOLDER.split("/"))
    assert w.drive.files[row.drive_file_id][1] == NEW_NAME
    assert w.drive.properties[row.drive_file_id]["unit"] == "Kerkstraat 12-2"
    assert _items(w, plan)[doc].status is ReorgItemStatus.moved
    assert _plan_status(w, plan) is ReorgPlanStatus.applied
    assert apply_plan(w.engine, w.drive, w.company_id, plan) == {}  # a repeat has nothing left to do
    assert len(w.drive.files) == 1


def test_nothing_moves_before_approval_or_after_a_rejection(w: World) -> None:
    doc = _filed(w)
    plan = build_plan(w.engine, w.company_id, "owner")
    assert plan is not None
    assert apply_plan(w.engine, w.drive, w.company_id, plan) == {}  # still only proposed
    assert decide_plan(w.engine, w.company_id, plan, False, None) is ReorgPlanStatus.rejected
    assert apply_plan(w.engine, w.drive, w.company_id, plan) == {}
    assert _doc(w, doc).drive_folder == OLD_FOLDER
    assert _items(w, plan)[doc].status is ReorgItemStatus.rejected


def test_partial_approval_moves_only_the_chosen_items(w: World) -> None:
    first, second = _filed(w), _filed(w)
    plan = build_plan(w.engine, w.company_id, "owner")
    assert plan is not None
    items = _items(w, plan)
    assert decide_plan(w.engine, w.company_id, plan, True, {items[first].id}) is ReorgPlanStatus.approved
    assert apply_plan(w.engine, w.drive, w.company_id, plan) == {"moved": 1}
    assert _doc(w, first).drive_folder == NEW_FOLDER
    assert _doc(w, second).drive_folder == OLD_FOLDER
    assert _items(w, plan)[second].status is ReorgItemStatus.rejected


def test_deciding_twice_keeps_the_first_decision(w: World) -> None:
    _filed(w)
    plan = build_plan(w.engine, w.company_id, "owner")
    assert plan is not None
    assert decide_plan(w.engine, w.company_id, plan, True, None) is ReorgPlanStatus.approved
    assert decide_plan(w.engine, w.company_id, plan, False, None) is ReorgPlanStatus.approved


def test_a_document_moved_since_the_plan_is_skipped_as_stale(w: World) -> None:
    doc = _filed(w)
    plan = build_plan(w.engine, w.company_id, "owner")
    assert plan is not None
    decide_plan(w.engine, w.company_id, plan, True, None)
    with Session(w.engine) as s, s.begin():
        row = s.get(DocumentRow, doc)
        assert row is not None
        row.drive_folder = "EstateOS/elsewhere"
    assert apply_plan(w.engine, w.drive, w.company_id, plan) == {"failed": 1}
    assert _doc(w, doc).drive_folder == "EstateOS/elsewhere"


def test_a_file_deleted_in_drive_fails_its_item_and_the_rest_still_move(w: World) -> None:
    gone, fine = _filed(w), _filed(w)
    plan = build_plan(w.engine, w.company_id, "owner")
    assert plan is not None
    decide_plan(w.engine, w.company_id, plan, True, None)
    del w.drive.files[_doc(w, gone).drive_file_id or ""]  # Harjot trashed it in Drive
    assert apply_plan(w.engine, w.drive, w.company_id, plan) == {"failed": 1, "moved": 1}
    assert _items(w, plan)[gone].status is ReorgItemStatus.failed
    assert _doc(w, fine).drive_folder == NEW_FOLDER
    assert _plan_status(w, plan) is ReorgPlanStatus.applied


class FlakyRelocate(MemoryDrive):
    def __init__(self) -> None:
        super().__init__()
        self.failures = 1

    def relocate(self, file_id: str, folder_id: str, name: str) -> None:
        if self.failures:
            self.failures -= 1
            raise DriveApiError("drive relocate failed (503)", status=503, retryable=True)
        super().relocate(file_id, folder_id, name)


def test_a_transient_drive_error_propagates_and_the_retry_finishes_the_job(
    migrated_engine: Engine, committed_company: Company
) -> None:
    flaky = FlakyRelocate()
    w = World(committed_company.id, new_id(), new_id(), flaky, migrated_engine)
    with Session(migrated_engine) as s, s.begin():
        since = date(2025, 1, 1)
        anna = Person(company_id=w.company_id, kind=PersonKind.tenant, display_name="Anna de Vries", valid_from=since)
        unit = Unit(company_id=w.company_id, label="Kerkstraat 12-2", valid_from=since)
        s.add_all([anna, unit])
        s.flush()
        w.anna, w.unit = anna.id, unit.id
    doc = _filed(w)
    plan = build_plan(w.engine, w.company_id, "owner")
    assert plan is not None
    decide_plan(w.engine, w.company_id, plan, True, None)
    with pytest.raises(DriveApiError):
        apply_plan(w.engine, flaky, w.company_id, plan)
    assert _doc(w, doc).drive_folder == OLD_FOLDER
    assert apply_plan(w.engine, flaky, w.company_id, plan) == {"moved": 1}
    assert _doc(w, doc).drive_folder == NEW_FOLDER


def test_a_removed_link_changes_where_it_belongs(w: World) -> None:
    doc = _filed(w)
    with Session(w.engine) as s, s.begin():
        link = s.scalars(
            select(DocumentLink).where(DocumentLink.document_id == doc, DocumentLink.kind == DocLinkKind.unit)
        ).one()
        link.method = "removed"
    plan = build_plan(w.engine, w.company_id, "owner")
    assert plan is not None
    assert _items(w, plan)[doc].to_folder == "EstateOS/_Unsorted/Leases/2026"


def test_only_filed_documents_with_a_drive_file_are_planned(w: World) -> None:
    review = _filed(w)
    with Session(w.engine) as s, s.begin():
        row = s.get(DocumentRow, review)
        assert row is not None
        row.status = DocumentStatus.review
    assert build_plan(w.engine, w.company_id, "owner") is None


def test_another_company_cannot_decide_or_apply_a_plan(w: World) -> None:
    _filed(w)
    plan = build_plan(w.engine, w.company_id, "owner")
    assert plan is not None
    with pytest.raises(NotFoundError):
        decide_plan(w.engine, new_id(), plan, True, None)
    with pytest.raises(NotFoundError):
        apply_plan(w.engine, w.drive, new_id(), plan)


def test_a_plan_can_be_limited_to_given_documents(w: World) -> None:
    one, two = _filed(w), _filed(w)
    plan = build_plan(w.engine, w.company_id, "system", [one])
    assert plan is not None
    assert set(_items(w, plan)) == {one}
    assert two not in _items(w, plan)
