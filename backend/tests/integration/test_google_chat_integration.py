"""Integration tests: Google Chat webhook handling, routing to owner_reply, and outbound delivery."""

import base64
import json
import time
from collections.abc import Iterator
from datetime import UTC, date, datetime
from typing import Any
from uuid import UUID

import pytest
from dbos import DBOS, DBOSClient
from fastapi.testclient import TestClient
from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from app.channels.gmail.drafts import FakeDrafts
from app.channels.gmail.fake import FakeMailbox, MemoryMailboxStore
from app.channels.google_chat.outbound import FakeGoogleChatOutbound
from app.channels.google_chat.verifier import ChatVerifier
from app.channels.whatsapp.outbound import FakeWhatsAppOutbound
from app.contracts import ActionType, Category, Channel, Direction, InteractiveChannel, Urgency
from app.core.settings import Settings
from app.db.enums import ActionStatus, ApprovalStatus, LinkMethod, PersonKind, RawEventStatus
from app.db.models import (
    ActionRow,
    Approval,
    ChannelAccount,
    Company,
    MessageRow,
    OwnerAccount,
    Person,
    RawEvent,
)
from app.ingestion import process
from app.main import create_app
from app.pipeline import case_repo
from app.sender.execute import SenderDeps
from app.workflows import owner_reply
from app.workflows.briefings import send_digest_chat
from app.workflows.deps import set_engine, set_sender_deps
from app.workflows.runtime import launch


def _wait_for(workflow_id: str) -> Any:
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        status = DBOS.retrieve_workflow(workflow_id).get_status()
        if status.status not in ("ENQUEUED", "PENDING"):
            assert status.status == "SUCCESS", f"{workflow_id}: {status.status} {status.error}"
            return status.output
        time.sleep(0.1)
    raise AssertionError(f"{workflow_id} did not finish")


pytestmark = pytest.mark.integration
NOW = datetime(2026, 10, 9, 8, 0, tzinfo=UTC)
MAILBOX = "beheer@estateos.test"
SPACE = "spaces/DM_HARJOT"
USER = "users/1001"
REPLY_PAYLOAD = {
    "channel": "gmail",
    "body_variants": [
        "Beste Sanne, we sturen een monteur.",
        "Beste Sanne, kunt u de thermostaat controleren?",
    ],
    "rationale": "Verwarming defect",
}


def _bearer_token(claims: dict[str, object] | None = None) -> str:
    claims = claims or {"iss": "chat@system.gserviceaccount.com", "sub": "test"}
    header = base64.urlsafe_b64encode(b'{"alg":"none"}').decode().rstrip("=")
    payload = base64.urlsafe_b64encode(json.dumps(claims).encode()).decode().rstrip("=")
    return f"Bearer {header}.{payload}.sig"


@pytest.fixture
def chat_env(
    test_settings: Settings,
    migrated_engine: Engine,
    committed_company: Company,
    dbos_client: DBOSClient,
) -> Iterator[tuple[TestClient, FakeGoogleChatOutbound, FakeDrafts, UUID, UUID]]:
    cid = committed_company.id
    with Session(migrated_engine) as s:
        s.add_all(
            [
                ChannelAccount(company_id=cid, channel=Channel.gmail, address=MAILBOX),
                ChannelAccount(company_id=cid, channel=Channel.google_chat, address=SPACE, is_owner_channel=True),
                OwnerAccount(
                    company_id=cid,
                    display_name="Harjot",
                    whatsapp_e164="+31612345678",
                    chat_user=USER,
                    interactive_channel=InteractiveChannel.google_chat,
                ),
            ]
        )
        person = Person(company_id=cid, kind=PersonKind.tenant, display_name="Sanne", valid_from=date(2026, 1, 1))
        s.add(person)
        s.flush()

        raw_in = RawEvent(company_id=cid, provider=Channel.gmail, provider_msg_id="p-1", payload={"mailbox": MAILBOX})
        s.add(raw_in)
        s.flush()

        msg = MessageRow(
            company_id=cid,
            raw_event_id=raw_in.id,
            channel=Channel.gmail,
            provider_msg_id="m-in",
            thread_ref="thr-101",
            sender_identity="sanne@example.test",
            direction=Direction.inbound,
            sent_at=NOW,
            text="Verwarming stuk",
            person_id=person.id,
            meta={"subject": "Verwarming stuk", "mailbox": MAILBOX, "thread_id": "thr-101"},
        )
        s.add(msg)
        s.flush()

        case_id = case_repo.create_case(s, cid, person.id, Category.maintenance, Urgency.high)
        case_repo.link_message(s, cid, case_id, msg.id, LinkMethod.new_case, None)

        action = ActionRow(
            company_id=cid,
            case_id=case_id,
            type=ActionType.reply_draft,
            status=ActionStatus.pending_approval,
            context_ref=[msg.id],
            rationale="Verwarming defect",
            payload=REPLY_PAYLOAD,
        )
        s.add(action)
        s.flush()

        approval = Approval(
            company_id=cid,
            action_id=action.id,
            draft_version=1,
            status=ApprovalStatus.pending,
        )
        s.add(approval)
        s.commit()
        approval_id = approval.id

    chat_outbound = FakeGoogleChatOutbound()
    drafts = FakeDrafts(FakeMailbox(MAILBOX, MemoryMailboxStore()))
    wa = FakeWhatsAppOutbound()

    DBOS.destroy()
    launch(test_settings, reset_for_tests=True, schedules=False)
    set_engine(migrated_engine)
    deps = SenderDeps(
        engine=migrated_engine,
        whatsapp=wa,
        gmail_drafts=lambda _a: drafts,
        google_chat=chat_outbound,
    )
    set_sender_deps(deps)

    verifier = ChatVerifier(provider="fake")
    app = create_app(
        test_settings,
        engine=migrated_engine,
        workflow_client=dbos_client,
        google_chat_verifier=verifier,
    )
    with TestClient(app) as client:
        yield client, chat_outbound, drafts, cid, approval_id

    set_sender_deps(None)
    set_engine(None)
    DBOS.destroy()


def test_google_chat_webhook_auth_failures(
    chat_env: tuple[TestClient, FakeGoogleChatOutbound, FakeDrafts, UUID, UUID],
) -> None:
    client, _, _, _, _ = chat_env
    # Missing auth
    res = client.post("/webhooks/googlechat", json={"type": "MESSAGE"})
    assert res.status_code == 401

    # Invalid auth
    res = client.post("/webhooks/googlechat", json={"type": "MESSAGE"}, headers={"authorization": "Bearer bad"})
    assert res.status_code == 401


def test_google_chat_webhook_unknown_sender_ignored(
    chat_env: tuple[TestClient, FakeGoogleChatOutbound, FakeDrafts, UUID, UUID],
    migrated_engine: Engine,
) -> None:
    client, _, _, _, _ = chat_env
    body = {
        "type": "MESSAGE",
        "space": {"name": "spaces/OTHER"},
        "user": {"name": "users/stranger"},
        "message": {"text": "hello"},
    }
    res = client.post("/webhooks/googlechat", json=body, headers={"authorization": _bearer_token()})
    assert res.status_code == 200

    # No RawEvent created for stranger
    with Session(migrated_engine) as session:
        raw_events = session.scalars(select(RawEvent).where(RawEvent.provider == Channel.google_chat)).all()
        assert len(raw_events) == 0


def test_google_chat_card_click_executes_approval_and_creates_draft(
    chat_env: tuple[TestClient, FakeGoogleChatOutbound, FakeDrafts, UUID, UUID],
    migrated_engine: Engine,
) -> None:
    client, _, drafts, cid, approval_id = chat_env

    # Simulate Harjot tapping "Send draft 1"
    body = {
        "type": "CARD_CLICKED",
        "space": {"name": SPACE},
        "user": {"name": USER, "displayName": "Harjot"},
        "message": {"name": f"{SPACE}/messages/card1"},
        "action": {
            "actionMethodName": "owner_action",
            "parameters": [{"key": "button_id", "value": f"apr:{approval_id}:d1"}],
        },
    }
    res = client.post("/webhooks/googlechat", json=body, headers={"authorization": _bearer_token()})
    assert res.status_code == 200

    # Check raw event was stored
    with Session(migrated_engine) as session:
        raw = session.scalar(
            select(RawEvent).where(RawEvent.company_id == cid, RawEvent.provider == Channel.google_chat)
        )
        assert raw is not None
        assert raw.status is RawEventStatus.pending

    # Process event through pipeline
    ingest_deps = process.IngestDeps(
        engine=migrated_engine,
        storage=None,  # type: ignore[arg-type]
        enqueuer=None,  # type: ignore[arg-type]
        gmail_mailbox=lambda _m: None,  # type: ignore[arg-type]
        whatsapp_media=lambda _p: None,  # type: ignore[arg-type]
        gmail_topic="topic",
    )
    persisted = process.persist_event(ingest_deps, raw.id)
    assert persisted.outcome == "processed"
    assert persisted.route == "owner"
    assert persisted.message_id is not None

    # Run owner_reply workflow
    kind = owner_reply.owner_reply(persisted.message_id)
    assert kind == "execute"

    # Verify approval state and draft creation
    with Session(migrated_engine) as session:
        appr = session.get(Approval, approval_id)
        assert appr is not None
        assert appr.status is ApprovalStatus.approved
        action_id = appr.action_id

    assert _wait_for(f"exec:{action_id}:1") in ("sent", "already")

    # Exactly one draft was created in the Gmail thread
    assert len(drafts.created) == 1
    created_draft = drafts.created[0]
    assert created_draft.thread_id == "thr-101"
    assert created_draft.body == "Beste Sanne, we sturen een monteur."


def test_google_chat_message_runs_command_and_delivers_reply_to_chat(
    chat_env: tuple[TestClient, FakeGoogleChatOutbound, FakeDrafts, UUID, UUID],
    migrated_engine: Engine,
) -> None:
    client, chat_outbound, _, cid, _ = chat_env

    body = {
        "type": "MESSAGE",
        "space": {"name": SPACE},
        "user": {"name": USER, "displayName": "Harjot"},
        "message": {"name": f"{SPACE}/messages/cmd1", "text": "help"},
    }
    res = client.post("/webhooks/googlechat", json=body, headers={"authorization": _bearer_token()})
    assert res.status_code == 200

    with Session(migrated_engine) as session:
        raw = session.scalar(
            select(RawEvent).where(
                RawEvent.company_id == cid,
                RawEvent.provider == Channel.google_chat,
                RawEvent.provider_msg_id == f"{SPACE}/messages/cmd1",
            )
        )
        assert raw is not None

    ingest_deps = process.IngestDeps(
        engine=migrated_engine,
        storage=None,  # type: ignore[arg-type]
        enqueuer=None,  # type: ignore[arg-type]
        gmail_mailbox=lambda _m: None,  # type: ignore[arg-type]
        whatsapp_media=lambda _p: None,  # type: ignore[arg-type]
        gmail_topic="topic",
    )
    persisted = process.persist_event(ingest_deps, raw.id)
    assert persisted.outcome == "processed"
    assert persisted.route == "owner"

    kind = owner_reply.owner_reply(persisted.message_id)
    assert kind == "command"

    # Verify response was sent to Google Chat space
    assert len(chat_outbound.sent) >= 1
    sent_space, sent_payload = chat_outbound.sent[0]
    assert sent_space == SPACE
    assert "commands" in sent_payload["text"].lower() or "tasks" in sent_payload["text"].lower()


def test_send_digest_chat_delivers_cards_v2_as_native_dict_payload(
    chat_env: tuple[TestClient, FakeGoogleChatOutbound, FakeDrafts, UUID, UUID],
    migrated_engine: Engine,
) -> None:
    _client, chat_outbound, _drafts, cid, _case_id = chat_env
    deps = SenderDeps(
        engine=migrated_engine,
        whatsapp=FakeWhatsAppOutbound(),
        gmail_drafts=lambda _addr: _drafts,
        google_chat=chat_outbound,
    )

    res = send_digest_chat(deps, cid, "briefing:chat-cards-1", "daily", NOW)
    assert res is not None

    # Crucial assertion: the payload delivered to Google Chat is a native cardsV2 dict,
    # NEVER stringified into a {"text": "{'cardsV2': ...}"} fallback!
    assert len(chat_outbound.sent) == 1
    sent_space, sent_payload = chat_outbound.sent[0]
    assert sent_space == SPACE
    assert "cardsV2" in sent_payload
    assert "text" not in sent_payload
    card = sent_payload["cardsV2"][0]["card"]
    assert "Daily Briefing" in card["header"]["title"]
    assert len(card["sections"]) >= 1
