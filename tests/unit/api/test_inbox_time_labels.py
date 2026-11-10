"""List and bubble time labels are the company's local clock, 24 h, with local day boundaries."""

from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from app.api.inbox.time_labels import when_label

AMS = ZoneInfo("Europe/Amsterdam")
NOW = datetime(2026, 11, 10, 9, 0, tzinfo=UTC)  # 10:00 in Amsterdam (CET, UTC+1)


def test_today_uses_the_local_clock_not_utc() -> None:
    assert when_label(datetime(2026, 11, 10, 8, 30, tzinfo=UTC), NOW, AMS) == "Today 09:30"


def test_a_message_just_after_local_midnight_is_today_even_though_utc_says_yesterday() -> None:
    assert when_label(datetime(2026, 11, 9, 23, 30, tzinfo=UTC), NOW, AMS) == "Today 00:30"


def test_yesterday_and_older() -> None:
    assert when_label(datetime(2026, 11, 9, 12, 0, tzinfo=UTC), NOW, AMS) == "Yesterday 13:00"
    assert when_label(datetime(2026, 10, 1, 12, 0, tzinfo=UTC), NOW, AMS) == "01 Oct 14:00"  # CEST, UTC+2


def test_weekday_form_within_a_week_only_when_asked() -> None:
    three_days = datetime(2026, 11, 7, 12, 0, tzinfo=UTC)
    assert when_label(three_days, NOW, AMS, weekdays=True) == "Sat 13:00"
    assert when_label(three_days, NOW, AMS) == "07 Nov 13:00"


def test_a_naive_timestamp_is_taken_as_utc() -> None:
    assert when_label(datetime(2026, 11, 10, 8, 30, tzinfo=UTC).replace(tzinfo=None), NOW, AMS) == "Today 09:30"
