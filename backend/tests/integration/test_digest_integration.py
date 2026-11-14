"""Integration tests: morning digest email delivery to owner_accounts.email."""

from datetime import UTC, date, datetime, timedelta
from uuid import UUID

import pytest
from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from app.channels.gmail.drafts import FakeDrafts
from app.channels.gmail.fake import FakeMailbox, MemoryMailboxStore
from app.channels.whatsapp.outbound import FakeWhatsAppOutbound
from app.contracts import ActionType, Category, Channel, Direction, InteractiveChannel, Urgency
from app.db.enums import ActionStatus, ApprovalStatus, SendStatus
from app.db.models import (
    ActionRow,
    Approval,
    Case,
    CaseLink,
    ChannelAccount,
    Company,
    MessageRow,
    OwnerAccount,
    Person,
    RawEvent,
    Send,
)
from app.sender.execute import SenderDeps
from app.workflows.briefings import send_digest_email

pytestmark = pytest.mark.integration
NOW = datetime(2026, 10, 9, 7, 30, tzinfo=UTC)
OWNER_EMAIL = "harjot@estateos.test"
MAILBOX = "beheer@estateos.test"


@pytest.fixture
def test_stack(migrated_engine: Engine) -> tuple[SenderDeps, FakeDrafts]:
    box = FakeMailbox(MAILBOX, MemoryMailboxStore())
    drafts = FakeDrafts(box)
    deps = SenderDeps(
        engine=migrated_engine,
        whatsapp=FakeWhatsAppOutbound(),
        gmail_drafts=lambda _addr: drafts,
    )
    return deps, drafts


def _seed_company_and_owner(
    session: Session,
    company: Company,
    *,
    owner_email: str = OWNER_EMAIL,
    interactive_channel: InteractiveChannel = InteractiveChannel.whatsapp,
) -> OwnerAccount:
    session.add(
        ChannelAccount(
            company_id=company.id,
            channel=Channel.gmail,
            address=MAILBOX,
            is_owner_channel=False,
        )
    )
    owner = OwnerAccount(
        company_id=company.id,
        display_name="Harjot",
        whatsapp_e164="+31612345678",
        email=owner_email,
        interactive_channel=interactive_channel,
    )
    session.add(owner)
    session.flush()
    return owner


def _add_reply_case(session: Session, company_id: UUID, thread_id: str = "thread-101") -> Approval:
    from app.db.models.directory import PersonKind

    person = Person(
        company_id=company_id,
        kind=PersonKind.tenant,
        display_name="Tenant Sanne",
        valid_from=date(2026, 1, 1),
    )
    session.add(person)
    session.flush()

    raw = RawEvent(company_id=company_id, provider=Channel.gmail, provider_msg_id="p-1", payload={"mailbox": MAILBOX})
    session.add(raw)
    session.flush()

    msg = MessageRow(
        company_id=company_id,
        raw_event_id=raw.id,
        channel=Channel.gmail,
        provider_msg_id="m-1",
        thread_ref=thread_id,
        sender_identity="sanne@example.com",
        direction=Direction.inbound,
        sent_at=NOW - timedelta(hours=2),
        text="Heizung ist kalt",
        meta={"thread_id": thread_id, "message_id": "m-1"},
    )
    session.add(msg)
    session.flush()

    case = Case(
        company_id=company_id,
        primary_person_id=person.id,
        category=Category.maintenance,
        urgency=Urgency.high,
        summary="Heater broken in apartment 4B",
    )
    session.add(case)
    session.flush()

    session.add(CaseLink(company_id=company_id, case_id=case.id, message_id=msg.id, method="thread"))

    action = ActionRow(
        company_id=company_id,
        case_id=case.id,
        type=ActionType.reply_draft,
        status=ActionStatus.pending_approval,
        context_ref=[msg.id],
        rationale="Verwarming kapot gemeld",
        payload={
            "channel": "gmail",
            "body_variants": [
                "Beste Sanne, we sturen een monteur.",
                "Beste Sanne, kunt u de thermostaat controleren?",
            ],
            "rationale": "Verwarming kapot gemeld",
        },
    )
    session.add(action)
    session.flush()

    approval = Approval(
        company_id=company_id,
        action_id=action.id,
        draft_version=1,
        status=ApprovalStatus.pending,
    )
    session.add(approval)
    session.flush()
    return approval


def test_send_digest_email_delivers_once_and_is_idempotent(
    migrated_engine: Engine,
    committed_company: Company,
    test_stack: tuple[SenderDeps, FakeDrafts],
) -> None:
    deps, fake_drafts = test_stack
    cid = committed_company.id

    with Session(migrated_engine) as session, session.begin():
        _seed_company_and_owner(session, committed_company)
        _add_reply_case(session, cid)

    # First call: delivers email
    key = "digest:test-day-1"
    ref1 = send_digest_email(deps, cid, key, "daily", NOW)
    assert ref1 is not None
    assert len(fake_drafts.sent) == 1
    assert len(fake_drafts.created) == 1
    assert fake_drafts.created[0].body == "Beste Sanne, we sturen een monteur."
    sent_req = fake_drafts.sent[0]
    assert sent_req.to == OWNER_EMAIL
    assert "Daily Briefing" in sent_req.subject
    assert "Tenant Sanne" in sent_req.body_text
    assert "Beste Sanne, we sturen een monteur." in sent_req.body_text

    # Verify audit record in sends table
    with Session(migrated_engine) as session:
        send_row = session.scalar(select(Send).where(Send.idempotency_key == key))
        assert send_row is not None
        assert send_row.status is SendStatus.sent
        assert send_row.target == OWNER_EMAIL
        assert send_row.channel is Channel.gmail

    # Second call with same key: idempotent no-op
    ref2 = send_digest_email(deps, cid, key, "daily", NOW)
    assert ref2 == ref1
    assert len(fake_drafts.sent) == 1  # not re-sent


def test_empty_day_sends_no_digest(
    migrated_engine: Engine,
    committed_company: Company,
    test_stack: tuple[SenderDeps, FakeDrafts],
) -> None:
    deps, fake_drafts = test_stack
    cid = committed_company.id

    with Session(migrated_engine) as session, session.begin():
        _seed_company_and_owner(session, committed_company)

    # Empty day: has_items is False
    res = send_digest_email(deps, cid, "digest:empty-day", "daily", NOW)
    assert res is None
    assert len(fake_drafts.sent) == 0


def test_no_interactive_channel_places_draft_in_gmail_thread(
    migrated_engine: Engine,
    committed_company: Company,
    test_stack: tuple[SenderDeps, FakeDrafts],
) -> None:
    deps, fake_drafts = test_stack
    cid = committed_company.id

    with Session(migrated_engine) as session, session.begin():
        owner = _seed_company_and_owner(session, committed_company)
        owner.interactive_channel = None  # type: ignore[assignment]
        _add_reply_case(session, cid, thread_id="thread-special-1")

    res = send_digest_email(deps, cid, "digest:no-interactive", "daily", NOW)
    assert res is not None

    # Both the digest email is sent AND a draft is created in the Gmail thread
    assert len(fake_drafts.sent) == 1
    assert len(fake_drafts.created) == 1
    created_draft = fake_drafts.created[0]
    assert created_draft.thread_id == "thread-special-1"
    assert created_draft.body == "Beste Sanne, we sturen een monteur."
