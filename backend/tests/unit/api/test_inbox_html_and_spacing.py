"""Regression tests for HTML email whitespace normalization and cached/optional HTML extraction."""

from app.api.inbox.routes import _cached_clean_and_html
from app.channels.gmail.html_sanitize import html_to_clean_text, normalize_message_whitespace


def test_normalize_collapses_table_spacers_and_excess_blank_lines() -> None:
    raw = "Sunday, 22 November 2026\r\n\u00a0\n\n\u200b\n\n\n\n3 guests · 19:00 - 21:15   \n\n\nContact\n"
    assert normalize_message_whitespace(raw) == ("Sunday, 22 November 2026\n\n3 guests · 19:00 - 21:15\n\nContact")


def test_html_to_clean_text_collapses_table_layout_blank_rows() -> None:
    html = (
        "<table><tr><td>&nbsp;</td></tr><tr><td>Sunday, 22 November 2026</td></tr>"
        "<tr><td><br><br><br></td></tr><tr><td>3 guests</td></tr></table>"
    )
    cleaned = html_to_clean_text(html)
    assert "\n\n\n" not in cleaned
    assert "Sunday, 22 November 2026" in cleaned
    assert "3 guests" in cleaned


def test_cached_clean_and_html_skips_sanitized_html_when_not_needed() -> None:
    raw_html = "<html><body><p>Hello</p><br><br><br><p>World</p></body></html>"
    html_none, plain_only = _cached_clean_and_html(raw_html, False)
    html_full, plain_with_html = _cached_clean_and_html(raw_html, True)

    assert html_none is None
    assert html_full is not None
    assert "<p>Hello</p>" in html_full
    assert plain_only == plain_with_html == "Hello\n\nWorld"
