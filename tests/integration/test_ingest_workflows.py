"""End-to-end ingestion with a real DBOS executor, real Postgres and fake providers."""

import threading
import time
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from email.message import EmailMessage
from typing import Any
from uuid import UUID

import pytest
from dbos import DBOS, DBOSClient
from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from app.channels.gmail.fake import FakeMailbox, MemoryMailboxStore
from app.channels.whatsapp.inbound import event_to_payload, parse_webhook
from app.channels.whatsapp.media import FakeWhatsAppMedia, MediaBlob, WhatsAppMediaError
from app.contracts import Channel, Direction
from app.core.settings import Settings
from app.core.workflow_names import GMAIL_SYNC_QUEUE, event_workflow_id
from app.db.enums import RawEventStatus
from app.db.models import AttachmentRow, ChannelAccount, Company, GmailSyncState, MessageRow, OwnerAccount, RawEvent
from app.ingestion import gmail_sync, process
from app.ingestion.process import REQUEUE_PREFIX, IngestDeps
from app.ingestion.repository import record_event
from app.storage.memory import MemoryStorage
from app.workflows import ingest
from app.workflows.deps import set_deps
from app.workflows.runtime import launch

pytestmark = pytest.mark.integration
Load = Callable[[str, str], bytes]
PNID, MAILBOX, OWNER = "100000000000001", "hausverwaltung@example.test", "+4915550000100"
OWNER_EMAIL = "harjot@example.test"
JPEG = b"\xff\xd8\xff\xe0 fake jpeg"


class FlakyMedia(FakeWhatsAppMedia):
    """Raises the queued errors one per call, then serves the blob."""

    def __init__(self) -> None:
        super().__init__({"MEDIA0002": MediaBlob(JPEG, "image/jpeg")})
        self.calls = 0
        self.errors: list[Exception] = [WhatsAppMediaError("503 from provider", retryable=True)]

    def download(self, media_id: str) -> MediaBlob:
        self.calls += 1
        if self.errors:
            raise self.errors.pop(0)
        return super().download(media_id)


@dataclass
class Env:
    company: Company
    whatsapp: ChannelAccount
    gmail: ChannelAccount
    mailbox: FakeMailbox
    storage: MemoryStorage
    media: FlakyMedia
    client: DBOSClient
    engine: Engine


@pytest.fixture
def env(test_settings: Settings, migrated_engine: Engine, committed_company: Company) -> Iterator[Env]:
    DBOS.destroy()
    launch(test_settings, reset_for_tests=True, schedules=False)  # executor runs here; no real crons
    client = DBOSClient(system_database_url=test_settings.dbos_database_url)
    with Session(migrated_engine, expire_on_commit=False) as s:
        wa = ChannelAccount(company_id=committed_company.id, channel=Channel.whatsapp, address=PNID)
        gm = ChannelAccount(company_id=committed_company.id, channel=Channel.gmail, address=MAILBOX)
        s.add_all(
            [
                wa,
                gm,
                OwnerAccount(
                    company_id=committed_company.id, display_name="Harjot", whatsapp_e164=OWNER, email=OWNER_EMAIL
                ),
            ]
        )
        s.commit()
    mailbox, storage, media = FakeMailbox(MAILBOX, MemoryMailboxStore()), MemoryStorage(), FlakyMedia()
    set_deps(
        IngestDeps(
            engine=migrated_engine,
            storage=storage,
            enqueuer=client,
            gmail_mailbox=lambda address: mailbox,
            whatsapp_media=lambda pnid: media,
            gmail_topic="projects/p/topics/gmail",
        )
    )
    yield Env(committed_company, wa, gm, mailbox, storage, media, client, migrated_engine)
    set_deps(None)
    client.destroy()
    DBOS.destroy()
    with Session(migrated_engine) as s:  # rows committed_company's cleanup does not know about
        s.query(OwnerAccount).filter(OwnerAccount.company_id == committed_company.id).delete()
        s.commit()


def finished(workflow_id: str, timeout: float = 30) -> Any:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        status = DBOS.retrieve_workflow(workflow_id).get_status()
        if status.status not in ("ENQUEUED", "PENDING"):
            return status
        time.sleep(0.1)
    raise AssertionError(f"{workflow_id} did not finish")


def wait(workflow_id: str, timeout: float = 30) -> Any:
    status = finished(workflow_id, timeout)
    assert status.status == "SUCCESS", f"{workflow_id}: {status.status} {status.error}"
    return status.output


def ingest_whatsapp(env: Env, recorded: Load, fixture: str) -> UUID:
    [event] = [e for e in parse_webhook(recorded("whatsapp", fixture)) if hasattr(e, "kind")]
    with Session(env.engine) as s, s.begin():
        raw_id = record_event(s, env.client, env.whatsapp, event.wamid, event_to_payload(event))  # type: ignore[arg-type]
    assert raw_id is not None
    return raw_id


def message_for(env: Env, raw_id: UUID) -> MessageRow:
    with Session(env.engine) as s:
        row = s.scalar(select(MessageRow).where(MessageRow.raw_event_id == raw_id))
        assert row is not None
        return row


def raw_status(env: Env, raw_id: UUID) -> RawEventStatus:
    with Session(env.engine) as s:
        raw = s.get(RawEvent, raw_id)
        assert raw is not None
        return raw.status


def test_tenant_text_is_stored_and_routed_to_pipeline(env: Env, recorded: Load) -> None:
    raw_id = ingest_whatsapp(env, recorded, "text")
    assert wait(event_workflow_id(raw_id)) == "processed"
    row = message_for(env, raw_id)
    assert (row.direction, row.sender_identity) == (Direction.inbound, "+4915550000001")
    assert raw_status(env, raw_id) is RawEventStatus.processed
    assert wait(f"pipe:{row.id}") == "stub"


def test_owner_button_reply_is_routed_to_owner_handler(env: Env, recorded: Load) -> None:
    raw_id = ingest_whatsapp(env, recorded, "template_button_reply")
    wait(event_workflow_id(raw_id))
    row = message_for(env, raw_id)
    assert row.meta["interactive_id"].startswith("apr:")
    assert wait(f"owner:{row.id}") == "stub"


def test_echo_is_stored_outbound_without_routing(env: Env, recorded: Load) -> None:
    raw_id = ingest_whatsapp(env, recorded, "echo")
    wait(event_workflow_id(raw_id))
    row = message_for(env, raw_id)
    assert row.direction is Direction.outbound
    assert DBOS.list_workflows(workflow_ids=[f"pipe:{row.id}", f"owner:{row.id}"]) == []


def test_image_retried_after_transient_media_error_and_stored(env: Env, recorded: Load) -> None:
    raw_id = ingest_whatsapp(env, recorded, "image_caption")
    wait(event_workflow_id(raw_id))
    assert env.media.calls == 2
    row = message_for(env, raw_id)
    with Session(env.engine) as s:
        [att] = s.scalars(select(AttachmentRow).where(AttachmentRow.message_id == row.id)).all()
    assert env.storage.get(att.s3_key) == JPEG


def test_unroutable_sender_is_failed_not_retried(env: Env) -> None:
    item = {"id": "wamid.ANON", "timestamp": "1759737600", "type": "text", "text": {"body": "hi"}}
    payload = {"v": 1, "kind": "message", "phone_number_id": PNID, "contact_name": None, "item": item}
    with Session(env.engine) as s, s.begin():
        raw_id = record_event(s, env.client, env.whatsapp, "wamid.ANON", payload)
    assert raw_id is not None
    assert wait(event_workflow_id(raw_id)) == "failed"
    assert raw_status(env, raw_id) is RawEventStatus.failed


def _mail(subject: str, sender: str = "Tenant 001 <tenant-001@example.test>") -> bytes:
    m = EmailMessage()
    m["From"] = sender
    m["To"] = MAILBOX
    m["Subject"] = subject
    m["Message-ID"] = f"<{subject}@example.test>"
    m.set_content(f"{subject} body")
    return m.as_bytes()


def _sync(env: Env, history: int) -> int:
    handle = env.client.enqueue(
        {
            "queue_name": GMAIL_SYNC_QUEUE,
            "workflow_name": "ingest.gmail_sync",
            "workflow_id": f"t:{history}:{time.time_ns()}",
        },
        str(env.gmail.id),
        history,
    )
    return int(wait(handle.workflow_id))


def _gmail_raws(env: Env) -> list[RawEvent]:
    with Session(env.engine) as s:
        return list(
            s.scalars(select(RawEvent).where(RawEvent.company_id == env.company.id, RawEvent.provider == Channel.gmail))
        )


def test_gmail_sync_records_processes_and_advances_cursor(env: Env) -> None:
    env.mailbox.add_message(_mail("heizung"), labels=["INBOX"])
    env.mailbox.add_message(_mail("draft"), labels=["DRAFT"], thread_id="t1")
    assert _sync(env, env.mailbox.current_history_id()) == 2  # first sync: bounded resync window
    raws = _gmail_raws(env)
    statuses = {r.provider_msg_id: wait(event_workflow_id(r.id)) for r in raws}
    assert sorted(statuses.values()) == ["ignored", "processed"]
    with Session(env.engine) as s:
        state = s.scalar(select(GmailSyncState).where(GmailSyncState.channel_account_id == env.gmail.id))
        assert state is not None
        assert int(state.history_id or 0) == env.mailbox.current_history_id()
    assert _sync(env, env.mailbox.current_history_id()) == 0  # stale/duplicate push is a no-op
    env.mailbox.add_message(_mail("nachtrag"), labels=["INBOX"])
    assert _sync(env, env.mailbox.current_history_id()) == 1  # incremental via history
    assert len(_gmail_raws(env)) == 3


def test_expired_history_resyncs_without_duplicates(env: Env) -> None:
    env.mailbox.add_message(_mail("one"), labels=["INBOX"])
    _sync(env, env.mailbox.current_history_id())
    env.mailbox.add_message(_mail("two"), labels=["INBOX"])
    env.mailbox.expire_history_before(env.mailbox.current_history_id() + 1)
    assert _sync(env, env.mailbox.current_history_id()) == 1
    assert len(_gmail_raws(env)) == 2


def test_watch_renew_and_backfill(env: Env) -> None:
    ingest.gmail_watch_renew(datetime.now(UTC), None)
    with Session(env.engine) as s:
        state = s.scalar(select(GmailSyncState).where(GmailSyncState.channel_account_id == env.gmail.id))
        assert state is not None
        assert state.watch_expires_at is not None
        assert state.watch_expires_at > datetime.now(UTC)
    env.mailbox.add_message(_mail("ohne-push"), labels=["INBOX"])
    now = datetime.now(UTC)
    ingest.gmail_backfill(now, None)  # no push arrived: the hourly backfill picks the mail up
    wait(ingest.backfill_workflow_id(str(env.gmail.id), now))
    assert len(_gmail_raws(env)) == 1


def _children(message_id: object) -> list[str]:
    ids = [f"pipe:{message_id}", f"owner:{message_id}"]
    return sorted(w.workflow_id for w in DBOS.list_workflows(workflow_ids=ids))


def test_rerun_after_commit_replays_routing_once(env: Env, recorded: Load) -> None:
    """A rerun after the work committed (`_already`) re-enqueues the same child id: one message, one child."""
    raw_id = ingest_whatsapp(env, recorded, "text")
    wait(event_workflow_id(raw_id))
    row = message_for(env, raw_id)
    deps = IngestDeps(env.engine, env.storage, env.client, lambda a: env.mailbox, lambda p: env.media, "t")
    assert process.persist_event(deps, raw_id).outcome == "duplicate"
    rerun = env.client.enqueue(
        {"queue_name": "pipeline", "workflow_name": "ingest.process_event", "workflow_id": f"evt:{raw_id}:x"},
        str(raw_id),
    )
    assert wait(rerun.workflow_id) == "duplicate"
    with Session(env.engine) as s:
        assert len(s.scalars(select(MessageRow).where(MessageRow.raw_event_id == raw_id)).all()) == 1
    assert _children(row.id) == [f"pipe:{row.id}"]


def test_unexpected_error_fails_event_then_requeue_recovers(env: Env, recorded: Load) -> None:
    env.media.errors = [RuntimeError("bug in media handling")]  # not transient: no step retries
    raw_id = ingest_whatsapp(env, recorded, "image_caption")
    assert finished(event_workflow_id(raw_id)).status == "ERROR"
    with Session(env.engine) as s:
        raw = s.get(RawEvent, raw_id)
        assert raw is not None
        assert (raw.status, raw.attempts) == (RawEventStatus.failed, 1)
        assert (raw.last_error or "").startswith(REQUEUE_PREFIX)
    ingest.requeue_failed(datetime.now(UTC), None)  # the bug is "fixed": media now serves the blob
    ingest.requeue_failed(datetime.now(UTC), None)  # a second sweep in the same state enqueues nothing new
    [rerun] = DBOS.list_workflows(workflow_id_prefix=f"evt:{raw_id}:r1:")  # attempt + hour bucket
    assert wait(rerun.workflow_id) == "processed"
    assert raw_status(env, raw_id) is RawEventStatus.processed
    assert _children(message_for(env, raw_id).id) == [f"pipe:{message_for(env, raw_id).id}"]


def test_data_failure_is_final_and_never_requeued(env: Env) -> None:
    item = {"id": "wamid.ANON2", "timestamp": "1759737600", "type": "text", "text": {"body": "hi"}}
    payload = {"v": 1, "kind": "message", "phone_number_id": PNID, "contact_name": None, "item": item}
    with Session(env.engine) as s, s.begin():
        raw_id = record_event(s, env.client, env.whatsapp, "wamid.ANON2", payload)
    assert wait(event_workflow_id(raw_id)) == "failed"
    deps = IngestDeps(env.engine, env.storage, env.client, lambda a: env.mailbox, lambda p: env.media, "t")
    assert raw_id not in [r for r, _ in process.requeue_candidates(deps)]


def test_spoofed_owner_email_is_routed_to_pipeline(env: Env) -> None:
    """From: is forgeable, so mail claiming to be the owner never reaches the owner command handler."""
    env.mailbox.add_message(_mail("freigabe", sender=f"Harjot <{OWNER_EMAIL}>"), labels=["INBOX"])
    assert _sync(env, env.mailbox.current_history_id()) == 1
    [raw] = _gmail_raws(env)
    assert wait(event_workflow_id(raw.id)) == "processed"
    row = message_for(env, raw.id)
    assert row.sender_identity == OWNER_EMAIL
    wait(f"pipe:{row.id}")
    assert _children(row.id) == [f"pipe:{row.id}"]


def test_concurrent_syncs_record_each_message_once(env: Env) -> None:
    """Two syncs racing past the queue (e.g. a manual run) both read Gmail; the cursor swap lets one win cleanly."""
    for subject in ("eins", "zwei", "drei"):
        env.mailbox.add_message(_mail(subject), labels=["INBOX"])
    deps = IngestDeps(env.engine, env.storage, env.client, lambda a: env.mailbox, lambda p: env.media, "t")
    history = env.mailbox.current_history_id()
    results: list[int] = []
    errors: list[BaseException] = []
    start = threading.Barrier(2)

    def run() -> None:
        start.wait()
        try:
            results.append(gmail_sync.sync_mailbox(deps, env.gmail.id, history))
        except BaseException as exc:  # surfaced below
            errors.append(exc)

    threads = [threading.Thread(target=run) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(30)
    assert errors == []
    assert sum(results) == 3
    assert len(_gmail_raws(env)) == 3


def _deps(env: Env) -> IngestDeps:
    return IngestDeps(env.engine, env.storage, env.client, lambda a: env.mailbox, lambda p: env.media, "t")


def test_event_stranded_in_pending_is_rerun_by_the_sweep(env: Env, recorded: Load) -> None:
    """A deploy during an outage strands the original workflow on old code: the raw event stays `pending`."""
    [event] = [e for e in parse_webhook(recorded("whatsapp", "text")) if hasattr(e, "kind")]
    with Session(env.engine) as s, s.begin():
        raw_id = record_event(s, env.client, env.whatsapp, event.wamid, event_to_payload(event), workflow=None)  # type: ignore[arg-type]
        assert raw_id is not None
        raw = s.get(RawEvent, raw_id)
        assert raw is not None
        raw.received_at = datetime.now(UTC) - timedelta(hours=2)
    ingest.requeue_failed(datetime.now(UTC), None)
    [rerun] = DBOS.list_workflows(workflow_id_prefix=f"evt:{raw_id}:p")
    assert wait(rerun.workflow_id) == "processed"
    assert raw_status(env, raw_id) is RawEventStatus.processed


def test_watch_renewal_racing_a_first_sync_both_succeed(env: Env) -> None:
    env.mailbox.add_message(_mail("parallel"), labels=["INBOX"])
    deps, history = _deps(env), env.mailbox.current_history_id()
    errors: list[BaseException] = []
    start = threading.Barrier(2)

    def run(fn: Callable[[], object]) -> None:
        start.wait()
        try:
            fn()
        except BaseException as exc:  # surfaced below
            errors.append(exc)

    jobs = [
        lambda: gmail_sync.renew_watch(deps, env.gmail.id, MAILBOX, env.company.id),
        lambda: gmail_sync.sync_mailbox(deps, env.gmail.id, history),
    ]
    threads = [threading.Thread(target=run, args=(job,)) for job in jobs]
    for t in threads:
        t.start()
    for t in threads:
        t.join(30)
    assert errors == []
    with Session(env.engine) as s:
        state = s.scalar(select(GmailSyncState).where(GmailSyncState.channel_account_id == env.gmail.id))
        assert state is not None
        assert state.watch_expires_at is not None
        assert state.history_id


class ArrivesDuringListing(FakeMailbox):
    """A mail lands between the resync listing and the history-id read (the window #8 of the M2 review)."""

    def message_ids_since(self, after: datetime) -> list[str]:
        ids = super().message_ids_since(after)
        if not getattr(self, "_arrived", False):
            self._arrived = True
            self.add_message(_mail("dazwischen"), labels=["INBOX"])
        return ids


def test_mail_arriving_during_a_resync_is_not_skipped(env: Env) -> None:
    mailbox = ArrivesDuringListing(MAILBOX, MemoryMailboxStore())
    mailbox.add_message(_mail("vorher"), labels=["INBOX"])
    deps = IngestDeps(env.engine, env.storage, env.client, lambda a: mailbox, lambda p: env.media, "t")
    assert gmail_sync.sync_mailbox(deps, env.gmail.id, mailbox.current_history_id()) == 1  # first sync: listing path
    assert gmail_sync.sync_mailbox(deps, env.gmail.id, mailbox.current_history_id()) == 1  # the late mail via history
    assert len(_gmail_raws(env)) == 2


def test_number_without_media_token_keeps_the_message(env: Env, recorded: Load) -> None:
    from app.core.errors import UnsafeConfigurationError

    def no_token(pnid: str) -> FakeWhatsAppMedia:
        raise UnsafeConfigurationError(f"no WhatsApp media credentials for phone_number_id {pnid}")

    deps = IngestDeps(env.engine, env.storage, env.client, lambda a: env.mailbox, no_token, "t")
    raw_id = ingest_whatsapp(env, recorded, "image_caption")
    assert process.persist_event(deps, raw_id).outcome == "processed"
    row = message_for(env, raw_id)
    assert row.meta["media_error"] == "UnsafeConfigurationError"


def test_last_requeue_keeps_the_message_without_its_media(env: Env, recorded: Load) -> None:
    """A media outage longer than all reruns must cost the photo, never the tenant's message."""
    [event] = [e for e in parse_webhook(recorded("whatsapp", "image_caption")) if hasattr(e, "kind")]
    with Session(env.engine) as s, s.begin():
        raw_id = record_event(s, env.client, env.whatsapp, event.wamid, event_to_payload(event), workflow=None)  # type: ignore[arg-type]
        assert raw_id is not None
        raw = s.get(RawEvent, raw_id)
        assert raw is not None
        raw.status, raw.attempts = RawEventStatus.failed, process.MAX_REQUEUES - 1
        raw.last_error = f"{REQUEUE_PREFIX} WhatsAppMediaError: 503"
    env.media.errors = [WhatsAppMediaError("503 from provider", retryable=True)] * 3
    deps = IngestDeps(env.engine, env.storage, env.client, lambda a: env.mailbox, lambda p: env.media, "t")
    assert process.persist_event(deps, raw_id).outcome == "processed"
    assert message_for(env, raw_id).meta["media_error"] == "WhatsAppMediaError"


def test_exhausted_requeues_are_logged_as_errors(env: Env, recorded: Load, caplog: pytest.LogCaptureFixture) -> None:
    from structlog.testing import capture_logs

    [event] = [e for e in parse_webhook(recorded("whatsapp", "text")) if hasattr(e, "kind")]
    with Session(env.engine) as s, s.begin():
        raw_id = record_event(s, env.client, env.whatsapp, event.wamid, event_to_payload(event), workflow=None)  # type: ignore[arg-type]
        assert raw_id is not None
        raw = s.get(RawEvent, raw_id)
        assert raw is not None
        raw.status, raw.attempts = RawEventStatus.failed, process.MAX_REQUEUES - 1
        raw.last_error = f"{REQUEUE_PREFIX} OperationalError: db"
    deps = IngestDeps(env.engine, env.storage, env.client, lambda a: env.mailbox, lambda p: env.media, "t")
    with capture_logs() as logs:
        process.mark_requeueable(deps, raw_id, "OperationalError: still down")
    assert any(e["event"] == "ingest.requeue_exhausted" and e["log_level"] == "error" for e in logs)
    assert raw_id not in [r for r, _ in process.requeue_candidates(deps)]


def test_stale_sweep_skips_events_whose_original_run_is_still_queued(env: Env, recorded: Load) -> None:
    [event] = [e for e in parse_webhook(recorded("whatsapp", "text")) if hasattr(e, "kind")]
    with Session(env.engine) as s, s.begin():
        raw_id = record_event(s, env.client, env.whatsapp, event.wamid, event_to_payload(event), workflow=None)  # type: ignore[arg-type]
        assert raw_id is not None
        raw = s.get(RawEvent, raw_id)
        assert raw is not None
        raw.received_at = datetime.now(UTC) - timedelta(hours=2)
    parked = {"queue_name": "parked", "workflow_name": "ingest.process_event", "workflow_id": event_workflow_id(raw_id)}
    env.client.enqueue(parked, str(raw_id))  # no executor serves this queue: the original stays ENQUEUED (backlog)
    assert raw_id in [r for r, _ in process.requeue_candidates(_deps(env))]
    assert str(raw_id) not in [r for r, _ in ingest.requeue_candidates_step()]


def test_mail_rescued_from_spam_is_ingested(env: Env) -> None:
    """First-time senders often land in spam: "Not spam" must still bring the mail into the pipeline."""
    spam = env.mailbox.add_message(_mail("erstkontakt"), labels=["SPAM"])
    assert _sync(env, env.mailbox.current_history_id()) == 1
    [raw] = _gmail_raws(env)
    assert wait(event_workflow_id(raw.id)) == "ignored"
    env.mailbox.move_to_inbox(spam)
    assert _sync(env, env.mailbox.current_history_id()) == 1
    rescued = next(r for r in _gmail_raws(env) if r.provider_msg_id == f"{spam}:inbox")
    assert wait(event_workflow_id(rescued.id)) == "processed"
    assert message_for(env, rescued.id).provider_msg_id == spam
    env.mailbox.move_to_inbox(spam)  # moved again: nothing new (the message exists now)
    assert _sync(env, env.mailbox.current_history_id()) == 0
