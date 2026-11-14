"""Pure parts of the owner's global search (the ⌘K palette): query cleaning and LIKE escaping."""

import pytest

from app.pipeline.global_search import MAX_QUERY_CHARS, MIN_QUERY_CHARS, clean_query, like_pattern


def test_like_pattern_escapes_wildcards_so_user_text_stays_literal() -> None:
    assert like_pattern("50%_off\\") == "%50\\%\\_off\\\\%"


def test_like_pattern_wraps_plain_text_for_contains_match() -> None:
    assert like_pattern("jansen") == "%jansen%"


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("  Jansen  ", "Jansen"),
        ("roof\n\tleak", "roof leak"),
        ("a", None),
        ("", None),
        ("   ", None),
        ("x" * (MAX_QUERY_CHARS + 50), "x" * MAX_QUERY_CHARS),
        ("ab", "ab"),
        ("ab\x00cd", "abcd"),
        ("\x00a\x07", None),
        ("jan​sen", "jan​sen"),
    ],
)
def test_clean_query(raw: str, expected: str | None) -> None:
    assert clean_query(raw) == expected


def test_min_query_length_is_two() -> None:
    assert MIN_QUERY_CHARS == 2
