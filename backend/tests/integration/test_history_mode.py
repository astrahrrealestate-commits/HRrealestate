"""History mode and Harjot's own mail in the pipeline (M13 T1)."""

from collections.abc import Iterator
from datetime import datetime, timedelta
from decimal import Decimal
from email.message import EmailMessage
from unittest.mock import patch
from uuid import UUID

import pytest
from dbos import DBOS, DBOSClient
from sqlalchemy import Engine, func, select
from sqlalchemy.orm import Session

from app.channels.gmail.fake import FakeMailbox, MemoryMailboxStore
from app.channels.prices.fake import FakePriceSource
from app.channels.whatsapp.media import FakeWhatsAppMedia
from app.contracts import Channel
from app.core.settings import Settings
from app.core.workflow_names import HISTORY_QUEUE, PIPELINE_QUEUE
from app.db.enums import DocumentStatus, FeedKind, PersonKind, PipelineStatus, RawEventStatus, WaitStatus
from app.db.models import (
    ActionRow,
    Approval,
    AttachmentRow,
    CaseLink,
    Company,
    DocumentRow,
    MessageChunk,
    MessageRow,
    OwnerFeed,
    QuoteReview,
    RawEvent,
    UnderstandingRow,
    WaitRow,
)
from app.finance.quotes import review_message
from app.ingestion import process
from app.ingestion.process import IngestDeps
from app.ingestion.repository import record_event, resolve_channel_account
from app.pipeline import work_repo
from app.storage.drive import MemoryDrive
from app.storage.memory import MemoryStorage
from app.workflows import documents, ingest, pipeline
from app.workflows.deps import set_deps, set_drive, set_engine, set_extractor
from app.workflows.mail_reload import run_history
from app.workflows.runtime import launch
from tests.integration.reload_support import HARJOT, MAILBOX, NOW, case, connect, mail, person

pytestmark = pytest.mark.integration


def _raw_gmail(sender: str, subject: str, body: str, *, sent_at: datetime, msg_id: str) -> bytes:
    em = EmailMessage()
    em["From"] = sender
    em["To"] = MAILBOX
    em["Subject"] = subject
    em["Message-ID"] = msg_id
    em["Date"] = sent_at.strftime("%a, %d %b %Y %H:%M:%S +0000")
    em.set_content(body)
    return em.as_bytes()


def _counts(engine: Engine, cid: UUID) -> dict[str, int]:
    with Session(engine) as s:
        return {
            name: int(s.scalar(select(func.count(m.id)).where(m.company_id == cid)) or 0)
            for name, m in (
                ("actions", ActionRow),
                ("approvals", Approval),
                ("feed", OwnerFeed),
                ("waits", WaitRow),
            )
        }


@pytest.fixture
def stack(test_settings: Settings, migrated_engine: Engine, committed_company: Company) -> Iterator[FakeMailbox]:
    connect(migrated_engine, committed_company.id)
    mailbox = FakeMailbox(MAILBOX, MemoryMailboxStore())
    storage = MemoryStorage()
    drive = MemoryDrive()
    DBOS.destroy()
    launch(test_settings, reset_for_tests=True, schedules=False)
    set_engine(migrated_engine)
    set_drive(drive)
    set_extractor(None)
    deps = IngestDeps(
        engine=migrated_engine,
        storage=storage,
        whatsapp_media=lambda _p: FakeWhatsAppMedia({}),
        gmail_mailbox=lambda _a: mailbox,
        enqueuer=DBOSClient(system_database_url=test_settings.dbos_database_url),
        gmail_topic="t",
    )
    set_deps(deps)
    yield mailbox
    set_deps(None)
    set_drive(None)
    set_engine(None)
    DBOS.destroy()


def test_history_mail_is_understood_linked_and_indexed_but_never_drafted(
    stack: FakeMailbox, migrated_engine: Engine, committed_company: Company
) -> None:
    del stack
    cid = committed_company.id
    m = mail(
        migrated_engine,
        cid,
        at=NOW - timedelta(days=20),
        text="De cv-ketel geeft storing F28 in mijn woning.",
        meta={"history": True, "subject": "CV storing"},
        status=PipelineStatus.pending,
    )
    assert DBOS.start_workflow(pipeline.pipeline_entry, str(m.message_id)).get_result() == "understood"
    with Session(migrated_engine) as s:
        assert s.scalar(select(UnderstandingRow.id).where(UnderstandingRow.message_id == m.message_id)) is not None
        assert s.scalar(select(CaseLink.case_id).where(CaseLink.message_id == m.message_id)) is not None
        assert s.scalar(select(MessageChunk.id).where(MessageChunk.company_id == cid)) is not None
    assert _counts(migrated_engine, cid) == {"actions": 0, "approvals": 0, "feed": 0, "waits": 0}


def test_history_attachment_gets_no_review_card(
    stack: FakeMailbox, migrated_engine: Engine, committed_company: Company
) -> None:
    del stack
    cid = committed_company.id
    m = mail(migrated_engine, cid, at=NOW - timedelta(days=5), meta={"history": True})
    with Session(migrated_engine) as s, s.begin():
        att = AttachmentRow(
            company_id=cid,
            message_id=m.message_id,
            s3_key="k",
            mime_type="application/pdf",
            size_bytes=4,
            sha256="b" * 64,
            filename="onbekend.pdf",
        )
        s.add(att)
        s.flush()
        att_id = att.id
        s.add(
            DocumentRow(
                company_id=cid,
                attachment_id=att_id,
                doc_type="other",
                title="Onbekend",
                file_name="onbekend.pdf",
                confidence=0.2,
                status=DocumentStatus.review,
            )
        )
    assert DBOS.start_workflow(documents.file_document_wf, str(cid), str(att_id), None).get_result() == "review"
    assert _counts(migrated_engine, cid)["feed"] == 0


def test_history_quote_gets_no_feed_card(
    test_settings: Settings, migrated_engine: Engine, committed_company: Company
) -> None:
    cid = committed_company.id
    connect(migrated_engine, cid)
    contractor = person(migrated_engine, cid, "Jan Bakker", kind=PersonKind.contractor)
    cid_case = case(migrated_engine, cid, contractor)
    m = mail(
        migrated_engine,
        cid,
        sender="bakker@reload.test",
        person_id=contractor,
        case_id=cid_case,
        at=NOW - timedelta(days=10),
        meta={"history": True, "subject": "Offerte dak"},
        text="Offerte dakreparatie: arbeid 1000 EUR excl BTW.",
    )
    src = FakePriceSource({"labour": [Decimal("45"), Decimal("50"), Decimal("55")]})
    review_id = review_message(migrated_engine, test_settings, m.message_id, today=NOW.date(), source=src)
    assert review_id is not None
    with Session(migrated_engine) as s:
        assert s.scalar(select(QuoteReview.id).where(QuoteReview.id == review_id)) is not None
        assert s.scalar(select(OwnerFeed.id).where(OwnerFeed.kind == FeedKind.quote_review)) is None


def test_history_never_sends_an_owner_notice(
    stack: FakeMailbox, migrated_engine: Engine, committed_company: Company
) -> None:
    del stack
    cid = committed_company.id
    m1 = mail(migrated_engine, cid, at=NOW - timedelta(days=5), meta={"history": True}, status=PipelineStatus.pending)
    with (
        patch.object(pipeline, "understand_step", return_value="budget"),
        patch.object(pipeline, "alert_budget_step") as budget_alert,
    ):
        assert DBOS.start_workflow(pipeline.pipeline_entry, str(m1.message_id)).get_result() == "blocked"
        budget_alert.assert_not_called()

    m2 = mail(
        migrated_engine,
        cid,
        thread="thr-err",
        at=NOW - timedelta(days=6),
        meta={"history": True},
        status=PipelineStatus.pending,
    )
    with (
        patch.object(pipeline, "understand_step", return_value="failed"),
        patch.object(pipeline, "final_failure_step", return_value=True),
        patch.object(pipeline, "link_step", return_value=str(m2.message_id)),
        patch.object(pipeline, "alert_unreadable_step") as unreadable_alert,
    ):
        assert DBOS.start_workflow(pipeline.pipeline_entry, str(m2.message_id)).get_result() == "failed"
        unreadable_alert.assert_not_called()
    assert _counts(migrated_engine, cid)["feed"] == 0


def test_live_mail_is_drafted_while_history_runs(
    stack: FakeMailbox, test_settings: Settings, migrated_engine: Engine, committed_company: Company
) -> None:
    del stack
    cid = committed_company.id
    hist_ids: set[str] = set()
    for i in range(20):
        m = mail(
            migrated_engine,
            cid,
            sender=f"hist{i}@reload.test",
            thread=f"thr-h-{i}",
            at=NOW - timedelta(days=30 - i),
            meta={"history": True},
            status=PipelineStatus.held,
        )
        hist_ids.add(str(m.message_id))
    client = DBOSClient(system_database_url=test_settings.dbos_database_url)
    assert run_history(migrated_engine, client, MAILBOX) == 20
    live = mail(
        migrated_engine,
        cid,
        sender="sanne@reload.test",
        thread="thr-live",
        at=NOW,
        text="Mijn raam sluit niet meer, kunnen we dit deze week herstellen?",
        meta={"subject": "Kapot raam"},
        status=PipelineStatus.pending,
    )
    with Session(migrated_engine) as s:
        live_wf = DBOS.start_workflow(pipeline.pipeline_entry, str(live.message_id)).get_result()
        assert live_wf == "understood"
        assert (s.scalar(select(func.count(ActionRow.id)).where(ActionRow.company_id == cid)) or 0) >= 1


def test_history_runs_one_senders_mail_in_sent_order(
    test_settings: Settings, migrated_engine: Engine, committed_company: Company
) -> None:
    cid = committed_company.id
    connect(migrated_engine, cid)
    m_new = mail(migrated_engine, cid, at=NOW - timedelta(days=5), meta={"history": True}, status=PipelineStatus.held)
    m_old = mail(migrated_engine, cid, at=NOW - timedelta(days=15), meta={"history": True}, status=PipelineStatus.held)
    m_mid = mail(migrated_engine, cid, at=NOW - timedelta(days=10), meta={"history": True}, status=PipelineStatus.held)
    seen: list[tuple[str, str]] = []

    class RecordingEnqueuer:
        def enqueue_in_transaction(self, _s: object, options: dict[str, object], msg_id: str) -> None:
            seen.append((msg_id, str(options["queue_partition_key"])))
            assert options["queue_name"] == HISTORY_QUEUE

    assert run_history(migrated_engine, RecordingEnqueuer(), MAILBOX) == 3
    assert [mid for mid, _ in seen] == [str(m_old.message_id), str(m_mid.message_id), str(m_new.message_id)]
    assert len({part for _, part in seen}) == 1
    del test_settings


def test_owner_authored_mail_is_linked_but_never_drafted(
    stack: FakeMailbox, test_settings: Settings, migrated_engine: Engine, committed_company: Company
) -> None:
    cid = committed_company.id
    gmail_id = stack.add_message(
        _raw_gmail(HARJOT, "Re: Lekkage", "Ik stuur morgenochtend de loodgieter.", sent_at=NOW, msg_id="<own1@r.test>"),
        labels=["INBOX"],
    )
    client = DBOSClient(system_database_url=test_settings.dbos_database_url)
    with Session(migrated_engine) as s, s.begin():
        acc = resolve_channel_account(s, Channel.gmail, MAILBOX)
        raw_id = record_event(
            s,
            client,
            acc,
            gmail_id,
            {"v": 1, "kind": "gmail", "mailbox": MAILBOX, "message_id": gmail_id},
            workflow=None,
        )
    assert raw_id is not None
    deps = IngestDeps(
        engine=migrated_engine,
        storage=MemoryStorage(),
        whatsapp_media=lambda _p: FakeWhatsAppMedia({}),
        gmail_mailbox=lambda _a: stack,
        enqueuer=client,
        gmail_topic="t",
    )
    persisted = process.persist_event(deps, raw_id)
    assert persisted.message_id is not None
    assert DBOS.start_workflow(pipeline.pipeline_entry, persisted.message_id).get_result() == "understood"
    with Session(migrated_engine) as s:
        row = s.get(MessageRow, UUID(persisted.message_id))
        assert row is not None
        assert row.meta.get("owner_authored") is True
        assert s.scalar(select(CaseLink.case_id).where(CaseLink.message_id == row.id)) is not None
    assert _counts(migrated_engine, cid) == {"actions": 0, "approvals": 0, "feed": 0, "waits": 0}


def test_old_mail_does_not_close_a_newer_wait(migrated_engine: Engine, committed_company: Company) -> None:
    cid = committed_company.id
    connect(migrated_engine, cid)
    p_id = person(migrated_engine, cid)
    c_id = case(migrated_engine, cid, p_id)
    with Session(migrated_engine) as s, s.begin():
        wait_id = work_repo.open_wait(s, cid, c_id, p_id, about="Reactie gevraagd", expected_by=NOW + timedelta(days=2))
        closed = work_repo.mark_received(s, cid, c_id, p_id, sent_at=NOW - timedelta(days=80))
    assert closed == []
    with Session(migrated_engine) as s:
        wait = s.get(WaitRow, wait_id)
        assert wait is not None
        assert wait.status is WaitStatus.waiting


def test_requeue_keeps_history_on_the_history_queue(
    test_settings: Settings, migrated_engine: Engine, committed_company: Company
) -> None:
    cid = committed_company.id
    connect(migrated_engine, cid)
    h_msg = mail(
        migrated_engine,
        cid,
        at=NOW - timedelta(days=10),
        meta={"history": True},
        status=PipelineStatus.failed,
    )
    l_msg = mail(migrated_engine, cid, thread="thr-l", at=NOW, status=PipelineStatus.failed)
    with Session(migrated_engine) as s, s.begin():
        acc = resolve_channel_account(s, Channel.gmail, MAILBOX)
        s.add(
            RawEvent(
                company_id=cid,
                provider=Channel.gmail,
                provider_msg_id="raw-hist-fail",
                payload={"history": True},
                status=RawEventStatus.failed,
                last_error=f"{process.REQUEUE_PREFIX} blip",
            )
        )
        s.add(
            RawEvent(
                company_id=cid,
                provider=Channel.gmail,
                provider_msg_id="raw-live-fail",
                payload={},
                status=RawEventStatus.failed,
                last_error=f"{process.REQUEUE_PREFIX} blip",
            )
        )
        del acc

    DBOS.destroy()
    launch(test_settings, reset_for_tests=True, schedules=False)
    set_engine(migrated_engine)
    try:
        hist_q, live_q = [], []
        with (
            patch.object(pipeline.queues, "history_queue") as hq,
            patch.object(pipeline.queues, "pipeline_queue") as pq,
        ):
            hq.return_value.enqueue.side_effect = lambda _fn, mid: hist_q.append(mid)
            pq.return_value.enqueue.side_effect = lambda _fn, mid: live_q.append(mid)
            pipeline.requeue_failed(NOW, None)
        assert str(h_msg.message_id) in hist_q
        assert str(l_msg.message_id) in live_q
        assert str(h_msg.message_id) not in live_q

        with Session(migrated_engine) as s:
            raw_h = s.scalar(select(RawEvent.id).where(RawEvent.provider_msg_id == "raw-hist-fail"))
            raw_l = s.scalar(select(RawEvent.id).where(RawEvent.provider_msg_id == "raw-live-fail"))
        set_deps(
            IngestDeps(
                engine=migrated_engine,
                storage=MemoryStorage(),
                whatsapp_media=lambda _p: FakeWhatsAppMedia({}),
                gmail_mailbox=lambda _a: FakeMailbox(MAILBOX, MemoryMailboxStore()),
                enqueuer=DBOSClient(system_database_url=test_settings.dbos_database_url),
                gmail_topic="t",
            )
        )
        ing_h, ing_l = [], []
        with (
            patch.object(ingest.queues, "history_queue") as hq,
            patch.object(ingest.queues, "pipeline_queue") as pq,
        ):
            hq.return_value.enqueue.side_effect = lambda _fn, rid: ing_h.append(rid)
            pq.return_value.enqueue.side_effect = lambda _fn, rid: ing_l.append(rid)
            ingest.requeue_failed(NOW, None)
        assert str(raw_h) in ing_h
        assert str(raw_l) in ing_l
        assert str(raw_h) not in ing_l
        assert PIPELINE_QUEUE != HISTORY_QUEUE
    finally:
        set_deps(None)
        set_engine(None)
        DBOS.destroy()
