"""The pure gate of an owner-typed WhatsApp send: plain values in, a refusal reason (or None) out."""

from datetime import UTC, datetime, timedelta
from typing import Any

from app.channels.whatsapp import payloads
from app.contracts import OutboundMode
from app.core.wa_window import WINDOW
from app.core.workflow_names import chat_workflow_id
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


def test_empty_and_whitespace_text_is_refused() -> None:
    assert refusal(text="") == "message is empty"
    assert refusal(text="  \n\t ") == "message is empty"


def test_text_over_the_whatsapp_limit_is_refused_and_at_the_limit_passes() -> None:
    assert refusal(text="x" * (payloads.TEXT_BODY_MAX + 1)) == "message is too long"
    assert refusal(text="x" * payloads.TEXT_BODY_MAX) is None


def test_gate_order_is_pause_mode_inbound_own_window_cap_text() -> None:
    worst: dict[str, Any] = {
        "paused": True,
        "mode": OutboundMode.draft,
        "inbound_at": None,
        "company_number": True,
        "recent_sends": 500,
        "text": "",
    }
    expected = [
        "company paused",
        "sending is switched off for this company",
        "no inbound message from this number",
        "this number belongs to the company",
        "hourly send cap reached",
        "message is empty",
    ]
    seen = []
    for key, fixed in (("paused", False), ("mode", OutboundMode.send), ("inbound_at", NOW), ("company_number", False)):
        seen.append(refusal(**worst))
        worst[key] = fixed
    worst["recent_sends"] = 500
    seen.append(refusal(**worst))
    worst["recent_sends"] = 0
    seen.append(refusal(**worst))
    assert seen == expected


def test_chat_workflow_id_is_the_send_key() -> None:
    assert chat_workflow_id("c", "m") == "chat:c:m"
