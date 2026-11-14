from datetime import UTC, date, datetime

from app.channels.brixx.query import build_filter, data_query_params


def test_build_filter_single() -> None:
    assert build_filter(("upddatetime", ">=", date(2024, 1, 1))) == "[upddatetime >= 2024-01-01]"


def test_build_filter_and() -> None:
    result = build_filter(("upddatetime", ">=", date(2024, 1, 1)), ("id", "=", 5))
    assert result == "[upddatetime >= 2024-01-01] and [id = 5]"


def test_build_filter_datetime_renders_date_only() -> None:
    assert build_filter(("d", "<", datetime(2024, 3, 9, 15, 30, tzinfo=UTC))) == "[d < 2024-03-09]"


def test_build_filter_string_value() -> None:
    assert build_filter(("name", "=", "abc")) == "[name = abc]"


def test_params_page_default() -> None:
    assert data_query_params(1, None, None) == {"page": "1"}


def test_params_filter_and_order() -> None:
    params = data_query_params(3, "[id > 1]", "id desc")
    assert params == {"page": "3", "filters": "[id > 1]", "orderby": "id desc"}
