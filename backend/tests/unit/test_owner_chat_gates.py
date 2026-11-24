"""The pure gate of an owner-typed WhatsApp send: plain values in, a refusal reason (or None) out."""

from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

import pytest

from app.channels.whatsapp import payloads
from app.contracts import OutboundMode
from app.core.wa_window import WINDOW
from app.core.workflow_names import chat_workflow_id
from app.db.models import MessageRow
from app.sender import owner_chat as oc

NOW = datetime(2026, 11, 24, 12, 0, tzinfo=UTC)


def refusal(**over: Any) -> str | None:
    args: dict[str, Any] = {
        "paused": False,
        "mode": OutboundMode.send,
        "inbound_at": NOW - timedelta(hours=1),
        "company_number": False,
        "now": NOW,
        "recent_sends": 0,
        "cap": 200,
        "recent_to_number": 0,
        "number_cap": 20,
        "text": "Dag mevrouw, de monteur komt morgen.",
    }
    return oc.chat_refusal(**{**args, **over})


def test_all_gates_clear_returns_none() -> None:
    assert refusal() is None


def test_paused_company_is_refused() -> None:
    assert refusal(paused=True) == "company paused"


def test_draft_and_missing_mode_are_refused() -> None:
    assert refusal(mode=OutboundMode.draft) == "sending is switched off for this company"
    assert refusal(mode=None) == "sending is switched off for this company"


def test_number_that_never_wrote_is_refused() -> None:
    assert refusal(inbound_at=None) == "no inbound message from this number"


def test_company_own_or_owner_number_is_refused() -> None:
    assert refusal(company_number=True) == "this number belongs to the company"


def test_window_exactly_at_the_boundary_is_closed() -> None:
    closed = "WhatsApp window closed: the contact wrote more than 23 h ago"
    assert refusal(inbound_at=NOW - WINDOW) == closed
    assert refusal(inbound_at=NOW - WINDOW + timedelta(seconds=1)) is None


def test_cap_at_200_refuses_and_199_passes() -> None:
    assert refusal(recent_sends=200, cap=200) == "hourly send cap reached"
    assert refusal(recent_sends=199, cap=200) is None


def test_per_number_cap_at_20_refuses_and_19_passes() -> None:
    assert refusal(recent_to_number=20, number_cap=20) == "too many messages to this number this hour"
    assert refusal(recent_to_number=19, number_cap=20) is None


def test_empty_and_whitespace_text_is_refused() -> None:
    assert refusal(text="") == "message is empty"
    assert refusal(text="  \n\t ") == "message is empty"


def test_text_over_the_whatsapp_limit_is_refused_and_at_the_limit_passes() -> None:
    assert refusal(text="x" * (payloads.TEXT_BODY_MAX + 1)) == "message is too long"
    assert refusal(text="x" * payloads.TEXT_BODY_MAX) is None


def test_gate_order_is_pause_mode_inbound_own_window_cap_number_cap_text() -> None:
    state: dict[str, Any] = {
        "paused": True,
        "mode": OutboundMode.draft,
        "inbound_at": None,
        "company_number": True,
        "recent_sends": 500,
        "recent_to_number": 500,
        "text": "",
    }
    fixes: list[tuple[str, Any]] = [
        ("paused", False),
        ("mode", OutboundMode.send),
        ("inbound_at", NOW - WINDOW),  # a number that wrote, but exactly at the closed boundary
        ("company_number", False),
        ("inbound_at", NOW),
        ("recent_sends", 0),
        ("recent_to_number", 0),
    ]
    seen = [refusal(**state)]
    for key, fixed in fixes:
        state[key] = fixed
        seen.append(refusal(**state))
    assert seen == [
        "company paused",
        "sending is switched off for this company",
        "no inbound message from this number",
        "this number belongs to the company",
        "WhatsApp window closed: the contact wrote more than 23 h ago",
        "hourly send cap reached",
        "too many messages to this number this hour",
        "message is empty",
    ]


def test_closed_window_is_reported_before_cap_and_text() -> None:
    reason = refusal(inbound_at=NOW - WINDOW, recent_sends=500, text="")
    assert reason == "WhatsApp window closed: the contact wrote more than 23 h ago"


CID = UUID(int=1)


def row(meta: dict[str, Any]) -> MessageRow:
    return MessageRow(meta=meta)


@pytest.mark.parametrize("value", ["abc123", "0197b3a6-7d1e-7cde-9f00-5a1c2d3e4f50", "a_b-C", "x" * 64])
def test_client_msg_id_charset_and_length_accepted(value: str) -> None:
    assert oc.chat_key(CID, row({"client_msg_id": value})) == f"chat:{CID}:{value}"


@pytest.mark.parametrize(
    "value", ["x" * 65, "", "a b", "a:b", "a/b", "\u00fcn\u00ef", "abc\n", "a\nb", 7, None, ["a"], {"a": 1}, True]
)
def test_client_msg_id_oversized_non_string_or_bad_charset_is_rejected(value: object) -> None:
    assert oc.chat_key(CID, row({"client_msg_id": value})) is None


def test_missing_client_msg_id_is_rejected() -> None:
    assert oc.chat_key(CID, row({})) is None


def test_chat_workflow_id_is_the_send_key() -> None:
    assert chat_workflow_id("c", "m") == "chat:c:m"
