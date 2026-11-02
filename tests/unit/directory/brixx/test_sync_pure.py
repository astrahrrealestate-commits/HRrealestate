"""Pure helpers of the BRIXX table sync: incremental filter, drift check, timestamp parsing."""

from datetime import UTC, date, datetime, timedelta, timezone

import pytest
import sqlalchemy as sa

from app.channels.brixx.models import BrixxField, BrixxTable
from app.core.errors import BrixxError, EstateOSError
from app.directory.brixx.schema import build_table
from app.directory.brixx.state import describe_error
from app.directory.brixx.sync import OVERLAP, detect_drift, incremental_filter, latest, parse_upddatetime
from tests.integration.brixx_support import plain_table_info, versioned_table_info


def test_overlap_is_five_minutes() -> None:
    assert timedelta(minutes=5) == OVERLAP


def test_first_run_has_no_filter() -> None:
    assert incremental_filter(versioned_table_info(), None) is None


def test_table_without_upddatetime_has_no_filter() -> None:
    since = datetime(2026, 10, 31, 12, 0, tzinfo=UTC)
    assert incremental_filter(plain_table_info(), since) is None


def test_filter_backs_off_overlap_and_a_full_day_in_amsterdam_time() -> None:
    since = datetime(2026, 10, 31, 12, 0, tzinfo=UTC)  # 13:00 Amsterdam (CET after the DST switch: 13:00)
    assert incremental_filter(versioned_table_info(), since) == "[upddatetime >= 2026-10-30]"


def test_filter_date_uses_amsterdam_not_utc() -> None:
    # 23:58 UTC on the 30th is 00:58 on the 31st in Amsterdam; minus 5 minutes and a day -> the 30th, not the 29th
    since = datetime(2026, 10, 30, 23, 58, tzinfo=UTC)
    assert incremental_filter(versioned_table_info(), since) == "[upddatetime >= 2026-10-30]"


def test_filter_uses_only_greater_or_equal() -> None:
    since = datetime(2026, 1, 15, 0, 2, tzinfo=timezone(timedelta(hours=-8)))
    result = incremental_filter(versioned_table_info(), since)
    assert result is not None
    assert result.startswith("[upddatetime >= ")
    assert " and " not in result
    assert "<" not in result


def test_naive_since_is_rejected() -> None:
    with pytest.raises(BrixxError):
        incremental_filter(versioned_table_info(), datetime.fromisoformat("2026-10-31T12:00:00"))


def test_drift_false_when_every_field_has_a_column() -> None:
    info = versioned_table_info()
    assert detect_drift(info, build_table(info, sa.MetaData())) is False


def test_drift_true_for_a_field_without_a_column() -> None:
    mirrored = build_table(versioned_table_info(), sa.MetaData())
    grown = BrixxTable(
        "PRG_DEMO",
        "ID",
        (*versioned_table_info().fields, BrixxField(9, "NIEUW", "VARCHAR(5)", False, None, None)),
    )
    assert detect_drift(grown, mirrored) is True


def test_naive_string_is_amsterdam_local_time() -> None:
    assert parse_upddatetime("2026-07-01 12:30:00") == datetime(2026, 7, 1, 10, 30, tzinfo=UTC)  # CEST, UTC+2
    assert parse_upddatetime("2026-01-01T12:30:00") == datetime(2026, 1, 1, 11, 30, tzinfo=UTC)  # CET, UTC+1


def test_aware_values_are_converted_not_reinterpreted() -> None:
    assert parse_upddatetime("2026-07-01T12:30:00+00:00") == datetime(2026, 7, 1, 12, 30, tzinfo=UTC)
    assert parse_upddatetime(datetime(2026, 7, 1, 12, 30, tzinfo=UTC)) == datetime(2026, 7, 1, 12, 30, tzinfo=UTC)


def test_date_value_is_amsterdam_midnight() -> None:
    assert parse_upddatetime(date(2026, 7, 1)) == datetime(2026, 6, 30, 22, 0, tzinfo=UTC)


@pytest.mark.parametrize("value", [None, "", "garbage", 17, {}])
def test_unparseable_values_are_none(value: object) -> None:
    assert parse_upddatetime(value) is None


def test_latest_ignores_none() -> None:
    early = datetime(2026, 1, 1, tzinfo=UTC)
    late = datetime(2026, 2, 1, tzinfo=UTC)
    assert latest(None, None) is None
    assert latest(early, None) == early
    assert latest(None, late) == late
    assert latest(late, early) == late


def test_error_text_has_class_table_and_page_but_no_message() -> None:
    class LeakyError(EstateOSError):
        pass

    text = describe_error(LeakyError("https://x/?ZOEKID=secret"), "PRG_DEMO", 3)
    assert text == "LeakyError table=PRG_DEMO page=3"
