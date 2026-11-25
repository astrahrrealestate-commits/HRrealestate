"""Pure rules of the chat read side."""

from app.contracts import Direction
from app.db.enums import DeliveryStatus
from app.pipeline import chat_repo


def test_chat_key_pattern_accepts_ascii_digits_only() -> None:
    assert chat_repo._E164.fullmatch("+31612345678")
    assert chat_repo._E164.fullmatch("+٣١٦١٢") is None  # Arabic-Indic digits


def test_is_pending_send_needs_our_client_id_and_no_status_or_error() -> None:
    ours = {"client_msg_id": "c1"}
    assert chat_repo.is_pending_send(Direction.outbound, None, ours) is True
    assert chat_repo.is_pending_send(Direction.outbound, None, {"echo": True}) is False
    assert chat_repo.is_pending_send(Direction.outbound, None, {}) is False
    assert chat_repo.is_pending_send(Direction.inbound, None, ours) is False
    assert chat_repo.is_pending_send(Direction.outbound, DeliveryStatus.sent, ours) is False
    assert chat_repo.is_pending_send(Direction.outbound, None, {**ours, "send_error": "x"}) is False
