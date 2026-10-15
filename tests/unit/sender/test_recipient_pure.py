"""Pure parts of the recipient guard: the window boundary and identity canonicalisation."""

from datetime import UTC, datetime, timedelta

from app.contracts import Channel, Direction
from app.db.models import MessageRow
from app.sender.owner_window import WINDOW
from app.sender.recipient import canonical, whatsapp_window_open

NOW = datetime(2026, 10, 15, 12, 0, tzinfo=UTC)


def _msg(age: timedelta, sent_age: timedelta | None = None) -> MessageRow:
    return MessageRow(
        channel=Channel.whatsapp, direction=Direction.inbound, created_at=NOW - age, sent_at=NOW - (sent_age or age)
    )


def test_window_is_the_owner_window_constant() -> None:
    assert WINDOW.total_seconds() == 23 * 3600


def test_window_open_inside_and_closed_at_or_after_the_boundary() -> None:
    assert whatsapp_window_open(_msg(timedelta(hours=22)), NOW)
    assert whatsapp_window_open(_msg(WINDOW - timedelta(seconds=1)), NOW)
    assert not whatsapp_window_open(_msg(WINDOW), NOW)
    assert not whatsapp_window_open(_msg(timedelta(hours=24)), NOW)


def test_older_provider_send_time_wins_as_the_anchor() -> None:
    assert not whatsapp_window_open(_msg(timedelta(hours=1), sent_age=timedelta(hours=24)), NOW)
    assert whatsapp_window_open(_msg(timedelta(hours=22), sent_age=timedelta(hours=1)), NOW)


def test_canonical_lowercases_email_and_formats_phone() -> None:
    assert canonical("  Huurder@Example.TEST ") == "huurder@example.test"
    assert canonical("+31 6 12345678") == "+31612345678"


def test_canonical_rejects_garbage() -> None:
    assert canonical("") is None
    assert canonical("not an identity") is None
