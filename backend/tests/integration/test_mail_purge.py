"""Purging one mailbox before a reload (M13 T2): what goes, what stays, every foreign key on the way, one company."""

from collections.abc import Sequence
from datetime import date, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID

import pytest
from sqlalchemy import Engine, func, select
from sqlalchemy.orm import Session

from app.contracts import ActionType, Channel
from app.core.ids import new_id
from app.db.base import CompanyScoped
from app.db.enums import (
    ActionStatus,
    ApprovalStatus,
    DocLinkKind,
    DocumentStatus,
    FeedKind,
    OutcomeLabel,
    OutcomeSource,
    QuoteSource,
    SendStatus,
)
from app.db.models import (
    ActionRevision,
    ActionRow,
    Approval,
    AttachmentRow,
    CalendarEventRow,
    Case,
    CaseLink,
    Company,
    DocumentLink,
    DocumentRow,
    MessageChunk,
    MessageRow,
    Outcome,
    OwnerFeed,
    Person,
    PriceSnapshot,
    QuoteLineRow,
    QuoteReview,
    QuoteRow,
    RawEvent,
    Send,
    TaskRow,
    TicketEdit,
    Timer,
    UnderstandingRow,
    WaitRow,
)
from app.pipeline import work_repo
from app.workflows.mail_purge import PurgeRefusedError, preview, purge
from tests.integration.reload_support import MAILBOX, NOW, case, connect, mail, person, understanding_body

pytestmark = pytest.mark.integration
CONFIRM = f"purge {MAILBOX}"


def _count(engine: Engine, model: type[CompanyScoped], company_id: UUID, *where: Any) -> int:
    with Session(engine) as s:
        return int(s.scalar(select(func.count(model.id)).where(model.company_id == company_id, *where)) or 0)


def _add(engine: Engine, *rows: Any) -> None:
    with Session(engine) as s, s.begin():
        s.add_all(rows)


def _action(engine: Engine, cid: UUID, case_id: UUID, context: Sequence[UUID]) -> tuple[UUID, UUID]:
    with Session(engine) as s, s.begin():
        row = ActionRow(
            company_id=cid,
            case_id=case_id,
            type=ActionType.reply_draft,
            rationale="r",
            context_ref=list(context),
            status=ActionStatus.approved,
            payload={"kind": "reply_draft", "channel": "gmail", "subject": None, "body_variants": ["a"]},
        )
        s.add(row)
        s.flush()
        approval = Approval(company_id=cid, action_id=row.id, draft_version=1, status=ApprovalStatus.approved)
        s.add_all([approval, ActionRevision(company_id=cid, action_id=row.id, draft_version=1, payload={},
                                            edited_by="owner")])  # fmt: skip
        s.flush()
        work_repo.create_task(s, cid, title="t", assignee="owner", source="approval", case_id=case_id, action_id=row.id)
        return row.id, approval.id


def _gmail_case(engine: Engine, cid: UUID) -> dict[str, UUID]:
    """A Gmail-only case with everything the pipeline makes from its mail."""
    tenant = person(engine, cid)
    case_id = case(engine, cid, tenant)
    m = mail(engine, cid, person_id=tenant, case_id=case_id, understood=understanding_body())
    action_id, approval_id = _action(engine, cid, case_id, [m.message_id])
    with Session(engine) as s, s.begin():
        att = AttachmentRow(company_id=cid, message_id=m.message_id, s3_key="k", mime_type="application/pdf",
                            size_bytes=3, sha256="a" * 64, filename="offerte.pdf")  # fmt: skip
        s.add(att)
        s.flush()
        doc = DocumentRow(company_id=cid, attachment_id=att.id, doc_type="quote", title="Offerte", file_name="f.pdf",
                          confidence=0.9, status=DocumentStatus.filed, drive_file_id="drive-1")  # fmt: skip
        quote = QuoteRow(company_id=cid, case_id=case_id, source=QuoteSource.message, source_id=m.message_id,
                         quote_date=date(2026, 11, 1), currency="EUR", total=Decimal("100"))  # fmt: skip
        s.add_all([doc, quote])
        s.flush()
        s.add_all([
            DocumentLink(company_id=cid, document_id=doc.id, kind=DocLinkKind.case, ref_id=case_id, method="message",
                         score=1.0),
            QuoteLineRow(company_id=cid, quote_id=quote.id, position=1, description="x", item_key="x",
                         quantity=Decimal(1), unit="job", amount=Decimal("100")),
            QuoteReview(company_id=cid, quote_id=quote.id, snapshot_basis="estimate_current_prices", verdict="ok",
                        overcharge=Decimal(0), late_days=0, report={}),
            OwnerFeed(company_id=cid, idempotency_key=f"{cid}:approval:{approval_id}:0", kind=FeedKind.approval,
                      ref_id=approval_id, payload={}),
            MessageChunk(company_id=cid, channel="gmail", thread_ref="thr-1", message_ids=[m.message_id],
                         first_message_id=m.message_id, last_message_id=m.message_id, first_sent_at=NOW,
                         last_sent_at=NOW, text="x", content_hash="h"),
        ])  # fmt: skip
    return {"case": case_id, "message": m.message_id, "action": action_id, "person": tenant}


def _whatsapp_case(engine: Engine, cid: UUID) -> dict[str, UUID]:
    tenant = person(engine, cid, "Tina")
    case_id = case(engine, cid, tenant)
    m = mail(engine, cid, channel=Channel.whatsapp, sender="+31611112222", thread="+31611112222", case_id=case_id,
             person_id=tenant)  # fmt: skip
    return {"case": case_id, "message": m.message_id, "person": tenant}


def test_purge_removes_gmail_data_and_raw_events_and_keeps_whatsapp_and_directory(
    migrated_engine: Engine, committed_company: Company
) -> None:
    cid = committed_company.id
    connect(migrated_engine, cid)
    gmail = _gmail_case(migrated_engine, cid)
    wa = _whatsapp_case(migrated_engine, cid)
    mixed = case(migrated_engine, cid, wa["person"])
    mail(migrated_engine, cid, case_id=mixed, thread="thr-2")
    kept = mail(migrated_engine, cid, channel=Channel.whatsapp, sender="+31611112222", thread="+31611112222",
                case_id=mixed)  # fmt: skip

    seen = preview(migrated_engine, MAILBOX)
    assert (seen.messages, seen.cases, seen.actions, seen.documents, seen.quotes) == (2, 1, 1, 1, 1)
    assert (
        _count(migrated_engine, MessageRow, cid, MessageRow.channel == Channel.gmail) == 2
    )  # a preview deletes nothing

    done = purge(migrated_engine, MAILBOX, confirm=CONFIRM)

    assert done.messages == seen.messages
    assert _count(migrated_engine, MessageRow, cid, MessageRow.channel == Channel.gmail) == 0
    assert _count(migrated_engine, RawEvent, cid, RawEvent.provider == Channel.gmail) == 0
    for model in (AttachmentRow, DocumentRow, DocumentLink, QuoteRow, QuoteLineRow, QuoteReview, ActionRow, Approval,
                  ActionRevision, TaskRow, OwnerFeed, MessageChunk, UnderstandingRow):  # fmt: skip
        assert _count(migrated_engine, model, cid) == 0, model.__tablename__
    assert _count(migrated_engine, Case, cid, Case.id == gmail["case"]) == 0
    assert _count(migrated_engine, Case, cid, Case.id.in_([wa["case"], mixed])) == 2  # WhatsApp keeps its cases
    assert _count(migrated_engine, CaseLink, cid, CaseLink.message_id == kept.message_id) == 1
    assert _count(migrated_engine, MessageRow, cid, MessageRow.channel == Channel.whatsapp) == 2
    assert _count(migrated_engine, Person, cid) == 2
    assert preview(migrated_engine, MAILBOX).messages == 0  # a second purge finds nothing


def test_purge_succeeds_with_sent_drafts_outcomes_and_waits(
    migrated_engine: Engine, committed_company: Company
) -> None:
    cid = committed_company.id
    connect(migrated_engine, cid)
    seeded = _gmail_case(migrated_engine, cid)
    case_id, action_id = seeded["case"], seeded["action"]
    with Session(migrated_engine) as s, s.begin():
        wait_id = work_repo.open_wait(s, cid, case_id, seeded["person"], about="Foto", expected_by=NOW,
                                      source_action_id=action_id)  # fmt: skip
        s.add_all([
            Send(company_id=cid, action_id=action_id, idempotency_key=f"exec:{action_id}:1", channel=Channel.gmail,
                 target="sanne@reload.test", status=SendStatus.sent),
            Outcome(company_id=cid, action_id=action_id, draft_version=1, final_text="a", label=OutcomeLabel.unchanged,
                    source=OutcomeSource.sent_folder),
            PriceSnapshot(company_id=cid, case_id=case_id, action_id=action_id, item_key="x", unit="job",
                          as_of=date(2026, 11, 1), low=Decimal(1), avg=Decimal(1), high=Decimal(1), sample_count=3,
                          basis="web"),
            CalendarEventRow(company_id=cid, case_id=case_id, title="Visit", start_time=NOW,
                             end_time=NOW + timedelta(hours=1)),
            TicketEdit(company_id=cid, case_id=case_id, fields={"title": "x"}),
        ])  # fmt: skip

    purge(migrated_engine, MAILBOX, confirm=CONFIRM)

    with Session(migrated_engine) as s:
        assert s.scalars(select(Send.action_id).where(Send.company_id == cid)).all() == [None]  # the log stays
        assert s.scalars(select(CalendarEventRow.case_id).where(CalendarEventRow.company_id == cid)).all() == [None]
        timers = s.scalars(
            select(Timer.id).where(Timer.company_id == cid, Timer.payload["wait_id"].astext == str(wait_id))
        )
        assert timers.all() == []
    for model in (Outcome, PriceSnapshot, WaitRow, TicketEdit, ActionRow):
        assert _count(migrated_engine, model, cid) == 0, model.__tablename__


def test_purge_is_scoped_to_one_company(migrated_engine: Engine, committed_company: Company) -> None:
    cid = committed_company.id
    connect(migrated_engine, cid)
    _gmail_case(migrated_engine, cid)
    with Session(migrated_engine, expire_on_commit=False) as s, s.begin():
        other = Company(name="Other BV")
        s.add(other)
    try:
        connect(migrated_engine, other.id, "info@other.test", "+31600008888")
        theirs = _gmail_case(migrated_engine, other.id)
        with Session(migrated_engine) as s, s.begin():  # their mail names our mailbox: still theirs
            s.get(MessageRow, theirs["message"]).meta = {"mailbox": MAILBOX}  # type: ignore[union-attr]

        purge(migrated_engine, MAILBOX, confirm=CONFIRM)

        assert _count(migrated_engine, MessageRow, cid) == 0
        assert _count(migrated_engine, MessageRow, other.id) == 1
        assert _count(migrated_engine, ActionRow, other.id) == 1
        assert _count(migrated_engine, Case, other.id) == 1
    finally:
        from tests.integration.conftest import purge_company

        purge_company(migrated_engine, other.id)


def test_another_mailbox_of_the_company_stays(migrated_engine: Engine, committed_company: Company) -> None:
    cid = committed_company.id
    connect(migrated_engine, cid)
    connect(migrated_engine, cid, "verhuur@reload.test", "+31600007777")
    mail(migrated_engine, cid, mailbox="verhuur@reload.test", thread="thr-9")
    mail(migrated_engine, cid)
    purge(migrated_engine, MAILBOX, confirm=CONFIRM)
    with Session(migrated_engine) as s:
        boxes = s.scalars(select(MessageRow.meta["mailbox"].astext).where(MessageRow.company_id == cid)).all()
    assert boxes == ["verhuur@reload.test"]


@pytest.mark.parametrize("typed", ["", "purge", f"purge {MAILBOX} ", "purge other@reload.test", "yes"])
def test_purge_refuses_without_the_typed_confirmation(
    migrated_engine: Engine, committed_company: Company, typed: str
) -> None:
    connect(migrated_engine, committed_company.id)
    mail(migrated_engine, committed_company.id)
    with pytest.raises(PurgeRefusedError):
        purge(migrated_engine, MAILBOX, confirm=typed)
    assert _count(migrated_engine, MessageRow, committed_company.id) == 1


def test_filed_documents_are_marked_in_drive_before_anything_is_deleted(
    migrated_engine: Engine, committed_company: Company
) -> None:
    cid = committed_company.id
    connect(migrated_engine, cid)
    _gmail_case(migrated_engine, cid)
    seen: list[tuple[UUID, list[tuple[str, str]], int]] = []

    def stamp(company_id: UUID, files: Sequence[tuple[str, str]]) -> None:
        seen.append((company_id, list(files), _count(migrated_engine, MessageRow, cid)))

    purge(migrated_engine, MAILBOX, confirm=CONFIRM, stamp=stamp)
    assert seen == [(cid, [("drive-1", "a" * 64)], 1)]


def test_a_failed_drive_mark_stops_the_purge(migrated_engine: Engine, committed_company: Company) -> None:
    cid = committed_company.id
    connect(migrated_engine, cid)
    _gmail_case(migrated_engine, cid)

    def broken(_company_id: UUID, _files: Sequence[tuple[str, str]]) -> None:
        raise RuntimeError("drive down")

    with pytest.raises(RuntimeError):
        purge(migrated_engine, MAILBOX, confirm=CONFIRM, stamp=broken)
    assert _count(migrated_engine, MessageRow, cid) == 1


def test_ids_are_never_shared_between_scopes() -> None:
    assert new_id() != new_id()
