"""The email HTML sanitizer must not be talked into emitting markup it did not allow."""

import re

import pytest

from app.channels.gmail.html_sanitize import sanitize_email_html

_ALLOWED_PAIR = re.compile(r"<style>.*?</style>", re.S)


@pytest.mark.parametrize(
    "payload",
    [
        "<style><<!--/style><img src=x onerror=alert(1)></style>",
        '<style><<!--!---->/style><meta http-equiv="refresh" content="0;url=https://evil.test"></style>',
        "<style>a{}</style/><img onerror=alert(1) src=x>",
        '<style/><p>zichtbaar</p><iframe src="https://evil.test"></iframe>',
    ],
)
def test_style_content_can_never_turn_into_markup(payload: str) -> None:
    out = sanitize_email_html(f"<p>hallo</p>{payload}") or ""
    assert "onerror" not in out
    assert "<meta" not in out
    assert "<iframe" not in out
    assert all("<" not in block[len("<style>") : -len("</style>")] for block in _ALLOWED_PAIR.findall(out))


def test_ordinary_style_blocks_are_kept_including_the_comment_wrapper() -> None:
    out = sanitize_email_html("<style><!-- p{color:#123456} --></style><p>hallo</p>")
    assert out == "<style> p{color:#123456} </style><p>hallo</p>"
