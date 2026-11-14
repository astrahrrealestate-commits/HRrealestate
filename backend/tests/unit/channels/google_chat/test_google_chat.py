"""Unit tests for Google Chat verifier, inbound event parsing, and cards rendering."""

import base64
import json
from datetime import UTC, datetime
from uuid import uuid4

import pytest

from app.channels.google_chat.inbound import (
    ChatParseError,
    GoogleChatEvent,
    parse_chat_event,
    to_message,
)
from app.channels.google_chat.outbound import FakeGoogleChatOutbound
from app.channels.google_chat.render import render_google_chat
from app.channels.google_chat.verifier import ChatAuthError, ChatVerifier
from app.contracts import Channel, Direction, OwnerChoice, OwnerMessage


def _fake_jwt(claims: dict[str, object]) -> str:
    header = base64.urlsafe_b64encode(b'{"alg":"none"}').decode().rstrip("=")
    payload = base64.urlsafe_b64encode(json.dumps(claims).encode()).decode().rstrip("=")
    return f"{header}.{payload}.sig"


# ---- Verifier tests ----


def test_verifier_accepts_valid_fake_token() -> None:
    verifier = ChatVerifier(project_number="1234567890", provider="fake")
    token = _fake_jwt({"iss": "chat@system.gserviceaccount.com", "aud": "1234567890", "sub": "bot"})
    claims = verifier.verify_token(f"Bearer {token}")
    assert claims["aud"] == "1234567890"
    assert claims["iss"] == "chat@system.gserviceaccount.com"


def test_verifier_rejects_missing_or_empty_token() -> None:
    verifier = ChatVerifier(provider="fake")
    with pytest.raises(ChatAuthError, match="missing bearer token"):
        verifier.verify_token(None)
    with pytest.raises(ChatAuthError, match="missing bearer token"):
        verifier.verify_token("Basic abc")
    with pytest.raises(ChatAuthError, match="empty bearer token"):
        verifier.verify_token("Bearer ")


def test_verifier_rejects_malformed_jwt() -> None:
    verifier = ChatVerifier(provider="fake")
    with pytest.raises(ChatAuthError, match="invalid fake token"):
        verifier.verify_token("Bearer not-a-jwt")


def test_verifier_rejects_wrong_issuer() -> None:
    verifier = ChatVerifier(provider="fake")
    token = _fake_jwt({"iss": "evil.issuer.com", "aud": "123"})
    with pytest.raises(ChatAuthError, match="unexpected issuer"):
        verifier.verify_token(f"Bearer {token}")


def test_verifier_rejects_wrong_audience() -> None:
    verifier = ChatVerifier(project_number="expected-project-123", provider="fake")
    token = _fake_jwt({"iss": "chat@system.gserviceaccount.com", "aud": "wrong-project-456"})
    with pytest.raises(ChatAuthError, match="unexpected audience"):
        verifier.verify_token(f"Bearer {token}")


# ---- Inbound event parsing tests ----


def test_parse_message_event() -> None:
    payload = {
        "type": "MESSAGE",
        "eventTime": "2026-10-09T08:00:00Z",
        "space": {"name": "spaces/AAAA123"},
        "user": {"name": "users/1001", "displayName": "Harjot Singh"},
        "message": {"name": "spaces/AAAA123/messages/msg001", "text": "tasks"},
    }
    event = parse_chat_event(payload)
    assert event.event_type == "MESSAGE"
    assert event.space_name == "spaces/AAAA123"
    assert event.user_name == "users/1001"
    assert event.user_display_name == "Harjot Singh"
    assert event.text == "tasks"
    assert event.button_id is None


def test_parse_card_clicked_event() -> None:
    payload = {
        "type": "CARD_CLICKED",
        "eventTime": "2026-10-09T08:05:00Z",
        "space": {"name": "spaces/AAAA123"},
        "user": {"name": "users/1001", "displayName": "Harjot Singh"},
        "action": {
            "actionMethodName": "owner_action",
            "parameters": [{"key": "button_id", "value": "apr:0191c95b-0000-7000-8000-000000000001:d1"}],
        },
    }
    event = parse_chat_event(payload)
    assert event.event_type == "CARD_CLICKED"
    assert event.space_name == "spaces/AAAA123"
    assert event.user_name == "users/1001"
    assert event.button_id == "apr:0191c95b-0000-7000-8000-000000000001:d1"


def test_parse_event_missing_space_raises() -> None:
    payload = {"type": "MESSAGE", "user": {"name": "users/1001"}}
    with pytest.raises(ChatParseError, match="missing space name"):
        parse_chat_event(payload)


def test_parse_event_missing_user_raises() -> None:
    payload = {"type": "MESSAGE", "space": {"name": "spaces/AAAA123"}}
    with pytest.raises(ChatParseError, match="missing user name"):
        parse_chat_event(payload)


def test_to_message_contract_conversion() -> None:
    now = datetime.now(UTC)
    event = GoogleChatEvent(
        event_type="CARD_CLICKED",
        event_time=now,
        space_name="spaces/AAAA123",
        user_name="users/1001",
        user_display_name="Harjot",
        message_name="spaces/AAAA123/messages/msg002",
        text="apr:test:ok",
        button_id="apr:test:ok",
    )
    cid = uuid4()
    raw_id = uuid4()
    msg, meta = to_message(event, company_id=cid, raw_event_id=raw_id)
    assert msg.channel is Channel.google_chat
    assert msg.direction is Direction.inbound
    assert msg.company_id == cid
    assert msg.raw_event_id == raw_id
    assert msg.sender_identity == "users/1001"
    assert msg.thread_ref == "spaces/AAAA123"
    assert meta["interactive_id"] == "apr:test:ok"
    assert meta["space"] == "spaces/AAAA123"


# ---- Renderer tests ----


def test_render_google_chat_plain_text() -> None:
    msg = OwnerMessage(text="Hello Harjot, here is your summary.")
    payload = render_google_chat(msg)
    assert payload == {"text": "Hello Harjot, here is your summary."}


def test_render_google_chat_cards_with_buttons() -> None:
    msg = OwnerMessage(
        text="Approve, edit or reject this draft.",
        choices=(
            OwnerChoice("apr:1:ok", "Approve"),
            OwnerChoice("apr:1:edit", "Edit"),
            OwnerChoice("apr:1:rej", "Reject"),
        ),
        header="Draft Review: Apt 4B",
    )
    payload = render_google_chat(msg)
    assert "cardsV2" in payload
    card = payload["cardsV2"][0]["card"]
    assert card["header"]["title"] == "Draft Review: Apt 4B"
    section = card["sections"][0]
    widgets = section["widgets"]
    assert widgets[0]["textParagraph"]["text"] == "Approve, edit or reject this draft."
    buttons = widgets[1]["buttonList"]["buttons"]
    assert len(buttons) == 3
    assert buttons[0]["text"] == "Approve"
    assert buttons[0]["onClick"]["action"]["parameters"][0] == {"key": "button_id", "value": "apr:1:ok"}
    assert buttons[1]["text"] == "Edit"
    assert buttons[2]["text"] == "Reject"


def test_fake_google_chat_outbound_records_sent() -> None:
    fake = FakeGoogleChatOutbound()
    msg_id = fake.send("spaces/AAAA123", {"text": "hi"})
    assert msg_id == "spaces/AAAA123/messages/fake-1"
    assert fake.sent == [("spaces/AAAA123", {"text": "hi"})]
