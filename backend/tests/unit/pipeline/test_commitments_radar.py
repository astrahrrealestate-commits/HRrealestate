from datetime import UTC, date, datetime
from zoneinfo import ZoneInfo

from app.contracts import Channel
from app.llm.agents.understanding import understanding_prompt
from app.pipeline.concierge_chase import _parse_target_due

AMS = "Europe/Amsterdam"


def test_parse_target_due_understands_weekdays_monthday_iso_and_duration() -> None:
    # Fri 2026-11-27 10:00 Amsterdam
    now = datetime(2026, 11, 27, 9, 0, tzinfo=UTC)

    tue = _parse_target_due("Tuesday", now, AMS)
    assert tue is not None
    assert tue.astimezone(ZoneInfo(AMS)).date() == date(2026, 12, 2)
    assert tue.astimezone(ZoneInfo(AMS)).hour == 9

    thirtieth = _parse_target_due("on the 30th", now, AMS)
    assert thirtieth is not None
    assert thirtieth.astimezone(ZoneInfo(AMS)).date() == date(2026, 12, 1)
    assert thirtieth.astimezone(ZoneInfo(AMS)).hour == 9

    iso = _parse_target_due("2026-12-05", now, AMS)
    assert iso is not None
    assert iso.astimezone(ZoneInfo(AMS)).date() == date(2026, 12, 6)

    dur = _parse_target_due("3d", now, AMS)
    assert dur is not None
    assert dur.astimezone(ZoneInfo(AMS)).date() == date(2026, 12, 1)


def test_understanding_prompt_includes_sent_date_when_supplied() -> None:
    prompt = understanding_prompt(
        "Ik stuur het dinsdag",
        Channel.gmail,
        subject="Documenten",
        sent_at=datetime(2026, 11, 27, 10, 0, tzinfo=UTC),
    )
    assert "Date: 2026-11-27 (Friday)" in prompt
