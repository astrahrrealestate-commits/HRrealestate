"""End to end with fakes: tenant email → understand → link → propose → approval card on Harjot's WhatsApp →
tap d2 → exactly one Gmail draft in the tenant's thread (M6/M7 done-when). Nothing reaches the tenant."""

import time
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

import pytest
from dbos import DBOS
from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from app.channels.gmail.drafts import FakeDrafts
from app.channels.gmail.fake import FakeMailbox, MemoryMailboxStore
from app.channels.whatsapp.outbound import FakeWhatsAppOutbound
from app.contracts import ButtonChoice, ButtonId, Channel, Direction
from app.core.ids import new_id
from app.core.settings import Settings
from app.db.enums import TimerStatus
from app.db.models import Approval, ChannelAccount, Company, MessageRow, OwnerAccount, RawEvent, Timer
from app.sender.execute import SenderDeps
from app.workflows import owner_reply, pipeline
from app.workflows.deps import set_engine, set_sender_deps
from app.workflows.runtime import launch

pytestmark = pytest.mark.integration
NOW = datetime(2026, 10, 7, 9, 0, tzinfo=UTC)
MAILBOX, OWNER, TENANT = "beheer@example.test", "+31600000100", "sanne@example.test"


@pytest.fixture
def stack(
    test_settings: Settings, migrated_engine: Engine, committed_company: Company
) -> Iterator[tuple[FakeWhatsAppOutbound, FakeDrafts]]:
    with Session(migrated_engine) as s, s.begin():
        s.add_all(
            [
                ChannelAccount(company_id=committed_company.id, channel=Channel.gmail, address=MAILBOX),
                OwnerAccount(company_id=committed_company.id, display_name="Harjot", whatsapp_e164=OWNER),
            ]
        )
    wa, drafts = FakeWhatsAppOutbound(), FakeDrafts(FakeMailbox(MAILBOX, MemoryMailboxStore()))
    DBOS.destroy()
    launch(test_settings, reset_for_tests=True, schedules=False)
    set_engine(migrated_engine)
    set_sender_deps(SenderDeps(migrated_engine, wa, lambda _a: drafts))
    yield wa, drafts
    set_sender_deps(None)
    set_engine(None)
    DBOS.destroy()


def _message(engine: Engine, cid: UUID, sender: str, text: str, channel: Channel, meta: dict[str, Any]) -> UUID:
    if channel is Channel.gmail:  # Gmail ingest always records the mailbox the thread lives in
        meta = {"mailbox": MAILBOX, **meta}
    with Session(engine) as s, s.begin():
        raw = RawEvent(company_id=cid, provider=channel, provider_msg_id=str(new_id()), payload={})
        s.add(raw)
        s.flush()
        m = MessageRow(
            company_id=cid,
            raw_event_id=raw.id,
            channel=channel,
            provider_msg_id=raw.provider_msg_id,
            thread_ref="thr-9" if channel is Channel.gmail else sender,
            sender_identity=sender,
            direction=Direction.inbound,
            sent_at=NOW,
            text=text,
            meta=meta,
        )
        s.add(m)
        s.flush()
        return m.id


def _wait(workflow_id: str) -> Any:
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        status = DBOS.retrieve_workflow(workflow_id).get_status()
        if status.status not in ("ENQUEUED", "PENDING"):
            assert status.status == "SUCCESS", f"{workflow_id}: {status.error}"
            return status.output
        time.sleep(0.1)
    raise AssertionError(workflow_id)


def test_email_to_card_to_single_gmail_draft(
    stack: tuple[FakeWhatsAppOutbound, FakeDrafts], migrated_engine: Engine, committed_company: Company
) -> None:
    wa, drafts = stack
    cid = committed_company.id
    _message(migrated_engine, cid, OWNER, "Goedemorgen", Channel.whatsapp, {})  # opens the 24 h window
    mid = _message(
        migrated_engine,
        cid,
        TENANT,
        "Overstroming! Er stroomt water uit het plafond van de badkamer.",
        Channel.gmail,
        {"subject": "Lekkage", "message_id": "<m9@example.test>", "from_name": "Sanne de Vries"},
    )
    assert DBOS.start_workflow(pipeline.pipeline_entry, str(mid)).get_result() == "understood"

    assert all(m.payload["to"] == OWNER.removeprefix("+") for m in wa.sent)  # only Harjot was messaged
    bodies = [m.payload.get("text", {}).get("body", "") for m in wa.sent]
    assert any("Reply: Sanne de Vries · maintenance" in b and "Draft 2:" in b for b in bodies)
    assert any("[EMERGENCY] Escalation" in str(m.payload) for m in wa.sent)

    with Session(migrated_engine) as s:
        reply_approval = s.scalar(
            select(Approval.id).where(Approval.company_id == cid).order_by(Approval.created_at).limit(1)
        )
    tap = ButtonId(approval_id=reply_approval, choice=ButtonChoice.d2).render()
    for _ in range(2):  # WhatsApp may deliver a tap twice
        owner_msg = _message(migrated_engine, cid, OWNER, "Send draft 2", Channel.whatsapp, {"interactive_id": tap})
        DBOS.start_workflow(owner_reply.owner_reply, str(owner_msg)).get_result()
    with Session(migrated_engine) as s:
        action_id = s.scalar(select(Approval.action_id).where(Approval.id == reply_approval))
    _wait(f"exec:{action_id}:1")
    assert len(drafts.created) == 1
    draft = drafts.created[0]
    assert (draft.thread_id, draft.to, draft.subject) == ("thr-9", TENANT, "Re: Lekkage")
    assert "foto" in draft.body.lower()  # draft 2 of the fake proposer asks for a photo


def test_company_without_owner_number_still_finishes_the_pipeline(
    test_settings: Settings, migrated_engine: Engine, committed_company: Company
) -> None:
    DBOS.destroy()
    launch(test_settings, reset_for_tests=True, schedules=False)
    set_engine(migrated_engine)
    try:
        mid = _message(migrated_engine, committed_company.id, TENANT, "Lekkage", Channel.gmail, {"subject": "Lek"})
        assert DBOS.start_workflow(pipeline.pipeline_entry, str(mid)).get_result() == "understood"
        with Session(migrated_engine) as s:
            assert s.scalar(select(Approval.id).where(Approval.company_id == committed_company.id)) is not None
    finally:
        set_engine(None)
        DBOS.destroy()


def test_closed_window_card_waits_until_harjot_writes(
    stack: tuple[FakeWhatsAppOutbound, FakeDrafts], migrated_engine: Engine, committed_company: Company
) -> None:
    wa, _ = stack
    cid = committed_company.id
    mid = _message(migrated_engine, cid, TENANT, "Lekkage", Channel.gmail, {"subject": "Lek"})
    DBOS.start_workflow(pipeline.pipeline_entry, str(mid)).get_result()
    assert [m.payload["type"] for m in wa.sent] == ["template"]
    hello = _message(migrated_engine, cid, OWNER, "Hoi", Channel.whatsapp, {})
    DBOS.start_workflow(owner_reply.owner_reply, str(hello)).get_result()
    assert "interactive" in [m.payload["type"] for m in wa.sent]


def test_overdue_wait_fires_through_the_timer_sweep_as_a_chaser_card(
    stack: tuple[FakeWhatsAppOutbound, FakeDrafts], migrated_engine: Engine, committed_company: Company
) -> None:
    from app.contracts import CaseState
    from app.db.models import WaitRow
    from app.pipeline import case_repo, work_repo
    from app.workflows import timer_dispatch

    wa, _ = stack
    cid = committed_company.id
    _message(migrated_engine, cid, OWNER, "Goedemorgen", Channel.whatsapp, {})
    mid = _message(migrated_engine, cid, TENANT, "Lekkage", Channel.gmail, {"subject": "Lek"})
    DBOS.start_workflow(pipeline.pipeline_entry, str(mid)).get_result()
    sent_before = len(wa.sent)
    with Session(migrated_engine) as s, s.begin():
        msg = s.get(MessageRow, mid)
        assert msg is not None
        case_id = case_repo.case_of_message(s, cid, mid)
        assert case_id is not None
        case_repo.transition(s, cid, case_id, CaseState.waiting_on_third_party, actor="system")
        wid = work_repo.open_wait(s, cid, case_id, msg.person_id, about="Foto", expected_by=NOW)
    assert DBOS.start_workflow(timer_dispatch.sweep_due, datetime.now(UTC)).get_result() >= 1
    deadline = time.monotonic() + 20
    while len(wa.sent) == sent_before and time.monotonic() < deadline:
        time.sleep(0.1)
    assert "Draft 1:" in str(wa.sent[sent_before].payload)
    with Session(migrated_engine) as s:
        assert s.scalar(select(WaitRow.chase_count).where(WaitRow.id == wid)) == 1


def test_due_briefing_timer_sends_one_briefing_and_schedules_the_next(
    stack: tuple[FakeWhatsAppOutbound, FakeDrafts], migrated_engine: Engine, committed_company: Company
) -> None:
    from app.pipeline import briefing, timers
    from app.workflows import timer_dispatch

    wa, _ = stack
    _message(migrated_engine, committed_company.id, OWNER, "Goedemorgen", Channel.whatsapp, {})
    with Session(migrated_engine) as s, s.begin():
        timers.schedule(
            s,
            committed_company.id,
            briefing.DAILY,
            datetime.now(UTC) - timedelta(minutes=1),
            {"kind": "daily"},
            dedupe_key="briefing.daily:test",
        )
    DBOS.start_workflow(timer_dispatch.sweep_due, datetime.now(UTC)).get_result()
    deadline = time.monotonic() + 20
    while not wa.sent and time.monotonic() < deadline:
        time.sleep(0.1)
    assert wa.sent[0].payload["text"]["body"].startswith("Good morning")
    with Session(migrated_engine) as s:
        kinds = s.scalars(
            select(Timer.kind).where(Timer.company_id == committed_company.id, Timer.status == TimerStatus.pending)
        ).all()
    assert set(kinds) >= {briefing.DAILY, briefing.WEEKLY}


def test_attachments_are_filed_or_reviewed_then_filed_on_the_owner_tap(
    stack: tuple[FakeWhatsAppOutbound, FakeDrafts],
    migrated_engine: Engine,
    committed_company: Company,
    test_settings: Settings,
) -> None:
    import hashlib

    from app.db.enums import DocumentStatus
    from app.db.models import AttachmentRow, DocumentRow
    from app.ingestion.process import IngestDeps
    from app.storage.drive import MemoryDrive
    from app.storage.memory import MemoryStorage
    from app.workflows.deps import set_deps, set_drive

    wa, _ = stack
    cid = committed_company.id
    storage, drive = MemoryStorage(), MemoryDrive()
    set_deps(
        IngestDeps(
            engine=migrated_engine,
            storage=storage,
            enqueuer=None,
            gmail_mailbox=None,  # type: ignore[arg-type]
            whatsapp_media=None,
            gmail_topic="t",
        )
    )  # type: ignore[arg-type]
    set_drive(drive)
    try:
        _message(migrated_engine, cid, OWNER, "Goedemorgen", Channel.whatsapp, {})
        mid = _message(migrated_engine, cid, TENANT, "Zie bijlagen", Channel.gmail, {"subject": "Bijlagen"})
        ids = {}
        with Session(migrated_engine) as s, s.begin():
            for name, mime in (("factuur_2026-09.pdf", "application/pdf"), ("IMG_1234.jpg", "image/jpeg")):
                data = (name * 3000).encode()
                key = storage.put(f"{cid}/{name}", data, mime).key
                att = AttachmentRow(
                    company_id=cid,
                    message_id=mid,
                    s3_key=key,
                    mime_type=mime,
                    filename=name,
                    size_bytes=len(data),
                    sha256=hashlib.sha256(data).hexdigest(),
                )
                s.add(att)
                s.flush()
                ids[name] = att.id
        DBOS.start_workflow(pipeline.pipeline_entry, str(mid)).get_result()
        assert _wait(f"doc:{ids['factuur_2026-09.pdf']}") == DocumentStatus.filed.value
        assert _wait(f"doc:{ids['IMG_1234.jpg']}") == DocumentStatus.review.value
        tap = f"doc:{ids['IMG_1234.jpg']}:photo"
        assert any(tap in str(m.payload) for m in wa.sent)  # the review card offers "File as photo"
        owner_msg = _message(migrated_engine, cid, OWNER, "File as photo", Channel.whatsapp, {"interactive_id": tap})
        assert DBOS.start_workflow(owner_reply.owner_reply, str(owner_msg)).get_result() == "document"
        assert _wait(f"doc:{ids['IMG_1234.jpg']}:owner:photo") == DocumentStatus.filed.value
        with Session(migrated_engine) as s:
            statuses = set(s.scalars(select(DocumentRow.status).where(DocumentRow.company_id == cid)))
        assert statuses == {DocumentStatus.filed}
        assert len(drive.files) == 2
    finally:
        set_deps(None)
        set_drive(None)


class _FlakyOnce(FakeWhatsAppOutbound):
    """Rate-limited on the first send, fine afterwards (WhatsApp 429)."""

    def __init__(self) -> None:
        super().__init__()
        self.failed = False

    def send(self, payload: dict[str, Any]) -> str:
        from app.channels.whatsapp.outbound import WhatsAppSendError

        if not self.failed:
            self.failed = True
            raise WhatsAppSendError("429 rate limited", code=130429, http_status=429, retryable=True, maybe_sent=False)
        return super().send(payload)


def test_a_transient_whatsapp_error_on_a_card_is_retried_not_fatal(
    test_settings: Settings, migrated_engine: Engine, committed_company: Company
) -> None:
    flaky, drafts = _FlakyOnce(), FakeDrafts(FakeMailbox(MAILBOX, MemoryMailboxStore()))
    with Session(migrated_engine) as s, s.begin():
        s.add_all(
            [
                ChannelAccount(company_id=committed_company.id, channel=Channel.gmail, address=MAILBOX),
                OwnerAccount(company_id=committed_company.id, display_name="Harjot", whatsapp_e164=OWNER),
            ]
        )
    DBOS.destroy()
    launch(test_settings, reset_for_tests=True, schedules=False)
    set_engine(migrated_engine)
    set_sender_deps(SenderDeps(migrated_engine, flaky, lambda _a: drafts))
    try:
        _message(migrated_engine, committed_company.id, OWNER, "Hoi", Channel.whatsapp, {})
        mid = _message(migrated_engine, committed_company.id, TENANT, "Lekkage", Channel.gmail, {"subject": "L"})
        assert DBOS.start_workflow(pipeline.pipeline_entry, str(mid)).get_result() == "understood"
        assert flaky.failed
        assert flaky.sent  # the card went out on the retry
    finally:
        set_sender_deps(None)
        set_engine(None)
        DBOS.destroy()
