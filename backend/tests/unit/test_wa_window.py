"""The shared WhatsApp 23 h window rule (`app.core.wa_window`) and its delegation from the sender."""

from datetime import UTC, datetime, timedelta

from app.contracts import Channel, Direction
from app.core.wa_window import WINDOW, window_closes_at, window_open
from app.db.models import MessageRow
from app.sender.recipient import whatsapp_window_open

NOW = datetime(2026, 11, 24, 12, 0, tzinfo=UTC)


def test_window_is_23_hours() -> None:
    assert timedelta(hours=23) == WINDOW


def test_window_open_just_inside() -> None:
    assert window_open(NOW - WINDOW + timedelta(seconds=1), NOW)


def test_window_closed_exactly_at_boundary() -> None:
    assert not window_open(NOW - WINDOW, NOW)


def test_window_closes_at_adds_window() -> None:
    received = NOW - timedelta(hours=3)
    assert window_closes_at(received) == received + WINDOW


def test_existing_sender_rule_unchanged() -> None:
    older = NOW - WINDOW - timedelta(seconds=1)
    msg = MessageRow(
        channel=Channel.whatsapp,
        direction=Direction.inbound,
        created_at=older,
        sent_at=NOW - timedelta(hours=1),  # newer than created_at: the older clock is the anchor
    )
    assert not whatsapp_window_open(msg, NOW)
    fresh = MessageRow(
        channel=Channel.whatsapp,
        direction=Direction.inbound,
        created_at=NOW - timedelta(hours=1),
        sent_at=NOW - timedelta(hours=2),
    )
    assert whatsapp_window_open(fresh, NOW)
