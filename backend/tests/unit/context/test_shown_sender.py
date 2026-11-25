import pytest

from app.context.shown_sender import greeting_name, shown_sender_name
from app.contracts import Channel
from app.db.models import MessageRow

JAN = "jan@example.test"


def message(channel: Channel = Channel.gmail, identity: str = JAN, **meta: str) -> MessageRow:
    return MessageRow(channel=channel, sender_identity=identity, meta=meta)


def test_a_mail_shows_the_name_in_its_own_headers_over_the_saved_contact_name() -> None:
    assert shown_sender_name(message(from_name="Jan de Vries"), "Harjot Singh") == "Jan de Vries"


def test_a_reply_to_without_a_name_shows_its_address() -> None:
    assert shown_sender_name(message(**{"from": JAN, "header_from": "harjot@example.test"}), "Saved Name") == JAN


def test_headers_without_any_name_show_the_address_even_when_from_and_reply_to_agree() -> None:
    assert shown_sender_name(message(**{"from": JAN}), "Saved Name") == JAN


def test_a_mail_with_no_header_details_shows_the_saved_name() -> None:
    assert shown_sender_name(message(), "Saved Name") == "Saved Name"


def test_a_mail_from_nobody_known_shows_its_address() -> None:
    assert shown_sender_name(message(), None) == JAN


@pytest.mark.parametrize(
    ("person", "meta", "expected"),
    [
        ("Saved Name", {"contact_name": "Profile"}, "Saved Name"),
        (None, {"contact_name": "Profile"}, "Profile"),
        (None, {}, "+31612345678"),
    ],
)
def test_a_chat_shows_the_saved_contact_then_the_profile_name_then_the_number(
    person: str | None, meta: dict[str, str], expected: str
) -> None:
    assert shown_sender_name(message(Channel.whatsapp, "+31612345678", **meta), person) == expected


@pytest.mark.parametrize(("name", "expected"), [("Jan de Vries", "Jan de Vries"), (JAN, None), ("+31612345678", None)])
def test_a_greeting_never_uses_an_address_as_a_name(name: str, expected: str | None) -> None:
    assert greeting_name(name) == expected


def test_a_header_name_cannot_hide_the_address_with_invisible_characters_or_length() -> None:
    hostile = "Jan\u202e\u2800\u200b  de\tVries " + "x" * 500
    shown = shown_sender_name(message(from_name=hostile), None)
    assert shown.startswith("Jan de Vries x")
    assert len(shown) <= 80


def test_a_name_of_only_invisible_characters_falls_back() -> None:
    assert shown_sender_name(message(from_name="\u200b\u2800"), None) == JAN


@pytest.mark.parametrize(
    "name",
    ["Betaal nu op www.evil.example vandaag", "Klik hier: http://x.test", "een twee drie vier vijf zes", "x" * 70],
)
def test_a_greeting_never_repeats_a_sentence_or_a_link(name: str) -> None:
    assert greeting_name(name) is None
