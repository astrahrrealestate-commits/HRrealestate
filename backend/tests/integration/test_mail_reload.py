"""Mailbox reload: reingest, run_history, settle, draft_open and Drive deduplication (M13 T2)."""

from datetime import timedelta
from email.message import EmailMessage
from typing import Any
from uuid import UUID

import pytest
from sqlalchemy import Engine, func, select
from sqlalchemy.orm import Session

from app.channels.gmail.fake import FakeMailbox, MemoryMailboxStore
from app.channels.whatsapp.media import FakeWhatsAppMedia
from app.contracts import CaseState, Channel, Direction
from app.core.settings import Settings
from app.core.workflow_names import HISTORY_QUEUE
from app.db.enums import DocumentStatus, MessageIndexStatus, PipelineStatus
from app.db.models import (
    ActionRow,
    AttachmentRow,
    Case,
    Company,
    DocumentRow,
    MessageIndexState,
    MessageRow,
    RawEvent,
)
from app.ingestion.process import IngestDeps
from app.pipeline import work_repo
from app.pipeline.documents import file_document
from app.storage.drive import CONTENT_PROPERTY, MemoryDrive, content_value
from app.storage.memory import MemoryStorage
from app.workflows.mail_draft_open import SkipReason, draft_open
from app.workflows.mail_reload import (
    HistoryNotDoneError,
    history_status,
    index_sent_history,
    reingest,
    run_history,
    settle_history,
)
from tests.integration.reload_support import HARJOT, MAILBOX, NOW, case, connect, mail, person, understanding_body

pytestmark = pytest.mark.integration


def _raw_email(sender: str, subject: str, body: str, msg_id: str) -> bytes:
    em = EmailMessage()
    em["From"] = sender
    em["To"] = MAILBOX
    em["Subject"] = subject
    em["Message-ID"] = msg_id
    em.set_content(body)
    return em.as_bytes()


class RecordingEnqueuer:
    def __init__(self) -> None:
        self.calls: list[tuple[dict[str, Any], tuple[Any, ...]]] = []

    def enqueue_in_transaction(self, _conn: Any, options: dict[str, Any], *args: Any) -> None:
        self.calls.append((dict(options), args))


def _deps(engine: Engine, mailbox: FakeMailbox, enqueuer: RecordingEnqueuer) -> IngestDeps:
    return IngestDeps(
        engine=engine,
        storage=MemoryStorage(),
        whatsapp_media=lambda _p: FakeWhatsAppMedia({}),
        gmail_mailbox=lambda _a: mailbox,
        enqueuer=enqueuer,
        gmail_topic="t",
    )


def _no_prepare(_engine: Engine, _settings: Settings, _message_id: UUID) -> None:
    return None


def test_reingest_records_held_history_events(migrated_engine: Engine, committed_company: Company) -> None:
    cid = committed_company.id
    connect(migrated_engine, cid)
    store = MemoryMailboxStore()
    mailbox = FakeMailbox(MAILBOX, store)
    for days_ago in (120, 80, 40, 10, 1):
        gid = mailbox.add_message(_raw_email("sanne@reload.test", "Mail", f"Dag {days_ago}", f"<{days_ago}@r.test>"),
                                  labels=["INBOX"])  # fmt: skip
        store.update(gid, lambda rec, _h, d=days_ago: rec.__setitem__(
            "internalDate", str(int((NOW - timedelta(days=d)).timestamp() * 1000))
        ))  # fmt: skip
    enq = RecordingEnqueuer()
    recorded = reingest(_deps(migrated_engine, mailbox, enq), MAILBOX, days=90)
    assert recorded == 4
    assert len(enq.calls) == 4
    assert all(opts["queue_name"] == HISTORY_QUEUE for opts, _ in enq.calls)
    with Session(migrated_engine) as s:
        rows = list(s.scalars(select(RawEvent).where(RawEvent.company_id == cid)).all())
        assert len(rows) == 4
        assert all(r.payload.get("history") is True for r in rows)


def test_reingest_twice_records_each_mail_once(migrated_engine: Engine, committed_company: Company) -> None:
    cid = committed_company.id
    connect(migrated_engine, cid)
    mailbox = FakeMailbox(MAILBOX, MemoryMailboxStore())
    mailbox.add_message(_raw_email("sanne@reload.test", "Mail", "Hallo", "<once@r.test>"), labels=["INBOX"])
    enq = RecordingEnqueuer()
    deps = _deps(migrated_engine, mailbox, enq)
    assert reingest(deps, MAILBOX, days=90) == 1
    assert reingest(deps, MAILBOX, days=90) == 0
    with Session(migrated_engine) as s:
        assert s.scalar(select(func.count(RawEvent.id)).where(RawEvent.company_id == cid)) == 1


def test_run_history_enqueues_oldest_first(migrated_engine: Engine, committed_company: Company) -> None:
    cid = committed_company.id
    connect(migrated_engine, cid)
    m_mid = mail(migrated_engine, cid, at=NOW - timedelta(days=10), status=PipelineStatus.held)
    m_new = mail(migrated_engine, cid, at=NOW - timedelta(days=2), status=PipelineStatus.held)
    m_old = mail(migrated_engine, cid, at=NOW - timedelta(days=25), status=PipelineStatus.held)
    enq = RecordingEnqueuer()
    assert run_history(migrated_engine, enq, MAILBOX) == 3
    assert [args[0] for _, args in enq.calls] == [str(m_old.message_id), str(m_mid.message_id), str(m_new.message_id)]
    with Session(migrated_engine) as s:
        statuses = set(s.scalars(select(MessageRow.pipeline_status).where(MessageRow.company_id == cid)).all())
        assert statuses == {PipelineStatus.pending}


def test_settle_resolves_idle_history_cases_only(migrated_engine: Engine, committed_company: Company) -> None:
    cid = committed_company.id
    connect(migrated_engine, cid)
    p = person(migrated_engine, cid)
    c_idle = case(migrated_engine, cid, p)
    c_recent = case(migrated_engine, cid, p)
    c_waiting = case(migrated_engine, cid, p)
    c_wa = case(migrated_engine, cid, p)
    mail(migrated_engine, cid, case_id=c_idle, thread="t1", at=NOW - timedelta(days=20), meta={"history": True})
    mail(migrated_engine, cid, case_id=c_recent, thread="t2", at=NOW - timedelta(days=3), meta={"history": True})
    mail(migrated_engine, cid, case_id=c_waiting, thread="t3", at=NOW - timedelta(days=20), meta={"history": True})
    mail(migrated_engine, cid, case_id=c_wa, channel=Channel.whatsapp, thread="+3161", at=NOW - timedelta(days=20))
    with Session(migrated_engine) as s, s.begin():
        work_repo.open_wait(s, cid, c_waiting, p, about="Wacht", expected_by=NOW)

    assert settle_history(migrated_engine, MAILBOX, idle_days=14) == 1
    with Session(migrated_engine) as s:
        assert s.get(Case, c_idle).state is CaseState.resolved  # type: ignore[union-attr]
        assert s.get(Case, c_recent).state is CaseState.open  # type: ignore[union-attr]
        assert s.get(Case, c_waiting).state is CaseState.open  # type: ignore[union-attr]
        assert s.get(Case, c_wa).state is CaseState.open  # type: ignore[union-attr]


def test_draft_open_drafts_only_the_newest_unanswered_mail_of_open_cases(
    test_settings: Settings, migrated_engine: Engine, committed_company: Company
) -> None:
    cid = committed_company.id
    connect(migrated_engine, cid)
    p = person(migrated_engine, cid)
    c_open = case(migrated_engine, cid, p)
    c_answered = case(migrated_engine, cid, p)
    mail(
        migrated_engine,
        cid,
        person_id=p,
        case_id=c_open,
        thread="to-1",
        at=NOW - timedelta(days=5),
        text="Eerste vraag over mijn cv-ketel.",
        understood=understanding_body(),
    )
    newest = mail(
        migrated_engine,
        cid,
        person_id=p,
        case_id=c_open,
        thread="to-1",
        at=NOW - timedelta(days=2),
        text="De monteur is niet geweest, wanneer komt er nu iemand kijken?",
        understood=understanding_body(),
    )
    mail(
        migrated_engine,
        cid,
        person_id=p,
        case_id=c_answered,
        thread="to-2",
        at=NOW - timedelta(days=3),
        text="Vraag",
        understood=understanding_body(),
    )
    mail(
        migrated_engine,
        cid,
        person_id=p,
        case_id=c_answered,
        thread="to-2",
        at=NOW - timedelta(days=1),
        direction=Direction.outbound,
        text="Antwoord",
    )
    report = draft_open(migrated_engine, test_settings, MAILBOX, dry_run=False, prepare=_no_prepare)
    assert report.drafted == (c_open,)
    assert (c_answered, SkipReason.answered) in report.skipped
    with Session(migrated_engine) as s:
        refs = list(s.scalars(select(ActionRow.context_ref).where(ActionRow.case_id == c_open)).all())
        assert refs == [[newest.message_id]]


def test_draft_open_skips_a_case_harjot_answered_in_quoted_history(
    test_settings: Settings, migrated_engine: Engine, committed_company: Company
) -> None:
    cid = committed_company.id
    connect(migrated_engine, cid)
    p = person(migrated_engine, cid)
    c_id = case(migrated_engine, cid, p)
    quoted_body = (
        "Dank voor je bericht.\n\n"
        f"Op 20 nov. 2026 om 10:00 schreef Harjot <{HARJOT}>:\n"
        "> De loodgieter komt vrijdag om 09:00."
    )
    mail(
        migrated_engine,
        cid,
        person_id=p,
        case_id=c_id,
        thread="t-q",
        at=NOW - timedelta(days=1),
        text=quoted_body,
        understood=understanding_body(requires_reply=False),
    )
    report = draft_open(migrated_engine, test_settings, MAILBOX, dry_run=False, prepare=_no_prepare)
    assert report.drafted == ()
    assert report.skipped == ((c_id, SkipReason.answered_in_quote),)


def test_draft_open_skips_cases_older_than_max_age(
    test_settings: Settings, migrated_engine: Engine, committed_company: Company
) -> None:
    cid = committed_company.id
    connect(migrated_engine, cid)
    p = person(migrated_engine, cid)
    c_id = case(migrated_engine, cid, p)
    mail(
        migrated_engine,
        cid,
        person_id=p,
        case_id=c_id,
        thread="t-old",
        at=NOW - timedelta(days=20),
        understood=understanding_body(),
    )
    report = draft_open(migrated_engine, test_settings, MAILBOX, max_age_days=14, dry_run=False, prepare=_no_prepare)
    assert report.drafted == ()
    assert report.skipped == ((c_id, SkipReason.too_old),)


def test_draft_open_dry_run_writes_nothing(
    test_settings: Settings, migrated_engine: Engine, committed_company: Company
) -> None:
    cid = committed_company.id
    connect(migrated_engine, cid)
    p = person(migrated_engine, cid)
    c_id = case(migrated_engine, cid, p)
    mail(
        migrated_engine,
        cid,
        person_id=p,
        case_id=c_id,
        thread="t-dry",
        at=NOW - timedelta(days=2),
        understood=understanding_body(),
    )
    called: list[UUID] = []

    def track(_e: Engine, _s: Settings, mid: UUID) -> None:
        called.append(mid)

    report = draft_open(migrated_engine, test_settings, MAILBOX, dry_run=True, prepare=track)
    assert report.drafted == (c_id,)
    assert called == []
    with Session(migrated_engine) as s:
        assert s.scalar(select(func.count(ActionRow.id)).where(ActionRow.company_id == cid)) == 0


def test_history_filing_does_not_duplicate_drive_files(
    test_settings: Settings, migrated_engine: Engine, committed_company: Company
) -> None:
    cid = committed_company.id
    connect(migrated_engine, cid)
    p = person(migrated_engine, cid)
    c_id = case(migrated_engine, cid, p)
    sha = "c" * 64
    drive = MemoryDrive()
    folder = drive.ensure_folder(("EstateOS", "Unsorted", "lease", "2026"))
    existing_id = drive.upload(
        "drive-existing-1",
        folder,
        "2026-11-01_lease_sanne_contract.pdf",
        "application/pdf",
        b"pdf-bytes",
        UUID("00000000-0000-0000-0000-000000000099"),
        properties={CONTENT_PROPERTY: content_value(cid, sha)},
    )
    storage = MemoryStorage()
    s3_key = f"{cid}/att.pdf"
    storage.put(s3_key, b"pdf-bytes", "application/pdf")
    m = mail(migrated_engine, cid, person_id=p, case_id=c_id, meta={"history": True})
    with Session(migrated_engine) as s, s.begin():
        att = AttachmentRow(
            company_id=cid,
            message_id=m.message_id,
            s3_key=s3_key,
            mime_type="application/pdf",
            size_bytes=9,
            sha256=sha,
            filename="huurcontract.pdf",
        )
        s.add(att)
        s.flush()
        att_id = att.id
    status = file_document(migrated_engine, test_settings, storage, drive, cid, att_id)
    assert status is DocumentStatus.filed
    assert len(drive.files) == 1
    with Session(migrated_engine) as s:
        row = s.scalar(select(DocumentRow).where(DocumentRow.attachment_id == att_id))
        assert row is not None
        assert row.drive_file_id == existing_id


def _unfinished_history(engine: Engine, cid: UUID) -> UUID:
    """A quiet open case, plus one reloaded mail the overnight run has not reached yet."""
    connect(engine, cid)
    p = person(engine, cid)
    quiet = case(engine, cid, p)
    old = NOW - timedelta(days=20)
    mail(engine, cid, person_id=p, case_id=quiet, thread="q1", at=old, meta={"history": True},
         understood=understanding_body())  # fmt: skip
    mail(engine, cid, thread="q2", at=old, meta={"history": True}, status=PipelineStatus.held)
    mail(engine, cid, thread="q3", at=old, meta={"history": True}, status=PipelineStatus.pending)
    return quiet


def test_settle_and_draft_open_wait_until_history_is_processed(
    test_settings: Settings, migrated_engine: Engine, committed_company: Company
) -> None:
    """Settling or drafting while reloaded mail is still queued resolves or answers a case whose newer mail is still
    on its way: both refuse until the run is done, unless forced."""
    quiet = _unfinished_history(migrated_engine, committed_company.id)
    with pytest.raises(HistoryNotDoneError, match="2 reloaded messages"):
        settle_history(migrated_engine, MAILBOX, idle_days=14)
    with pytest.raises(HistoryNotDoneError):
        draft_open(migrated_engine, test_settings, MAILBOX, dry_run=False, prepare=_no_prepare)
    draft_open(migrated_engine, test_settings, MAILBOX, dry_run=True, prepare=_no_prepare)  # lists, never refuses
    with Session(migrated_engine) as s:
        assert s.get(Case, quiet).state is CaseState.open  # type: ignore[union-attr]
    assert settle_history(migrated_engine, MAILBOX, idle_days=14, force=True) == 1


def test_history_status_counts_the_reloaded_mail_by_pipeline_state(
    migrated_engine: Engine, committed_company: Company
) -> None:
    _unfinished_history(migrated_engine, committed_company.id)
    assert history_status(migrated_engine, MAILBOX) == {"held": 1, "pending": 1, "failed": 0, "done": 1}


def test_sent_only_threads_are_indexed_for_astra(
    test_settings: Settings, migrated_engine: Engine, committed_company: Company
) -> None:
    """A reloaded thread that holds only Harjot's own mail has no inbound mail for the history run to start from, so
    nothing would ever index what he wrote; a thread with a tenant's mail is left to that mail's run."""
    cid = committed_company.id
    connect(migrated_engine, cid)
    old = NOW - timedelta(days=10)
    promise = "Beste Bram, ik zorg dat de buren vrijdag een brief krijgen."
    alone = mail(migrated_engine, cid, direction=Direction.outbound, thread="sent-only", at=old, text=promise,
                 meta={"history": True})  # fmt: skip
    mail(migrated_engine, cid, thread="both", at=old, meta={"history": True}, status=PipelineStatus.held)
    paired = mail(migrated_engine, cid, direction=Direction.outbound, thread="both", at=old, meta={"history": True})
    assert index_sent_history(migrated_engine, test_settings, MAILBOX) == 1
    assert index_sent_history(migrated_engine, test_settings, MAILBOX) == 0  # a rerun indexes nothing twice
    with Session(migrated_engine) as s:
        states = dict(s.execute(select(MessageIndexState.message_id, MessageIndexState.status)).all())
    assert states.get(alone.message_id) is MessageIndexStatus.indexed
    assert paired.message_id not in states
