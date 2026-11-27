"""Draft requests the Super Agent cannot honour silently: another channel than asked, or a rewrite."""

import pytest

from app.api.agent.draft_requests import channel_note, rewrite_answer


@pytest.mark.parametrize(
    "query",
    [
        "Make it shorter",
        "make the reply firmer",
        "Translate that draft to English",
        "rewrite this message",
        "Can you reword the email?",
        "put it in Dutch",
        "make it more formal",
    ],
)
def test_a_rewrite_request_is_routed_not_refused(query: str) -> None:
    assert rewrite_answer(query) is None


@pytest.mark.parametrize(
    "query",
    ["Draft a reply to Mohammed", "What should I do first?", "Translate the word huur", "Show the shorter route"],
)
def test_other_requests_are_not_intercepted(query: str) -> None:
    assert rewrite_answer(query) is None


def test_asking_for_whatsapp_but_getting_an_email_draft_is_said() -> None:
    note = channel_note("Draft a WhatsApp reply to Mohammed", "gmail", "mohammed@example.test")
    assert "WhatsApp" in note
    assert "email" in note.lower()
    assert "mohammed@example.test" in note


def test_asking_for_email_but_getting_a_whatsapp_draft_is_said() -> None:
    note = channel_note("Write him an email", "whatsapp", "+31612345678")
    assert "email" in note.lower()
    assert "WhatsApp" in note


@pytest.mark.parametrize(
    ("query", "channel"),
    [("Draft a WhatsApp reply", "whatsapp"), ("Draft an email", "gmail"), ("Draft a reply", "gmail"), ("hi", None)],
)
def test_no_note_when_the_channel_is_as_asked_or_not_asked(query: str, channel: str | None) -> None:
    assert channel_note(query, channel, "x") == ""
