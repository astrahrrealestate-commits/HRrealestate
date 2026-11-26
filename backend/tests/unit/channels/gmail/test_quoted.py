"""Splitting a mail into its new part and the history quoted below it (M13 T1)."""

import time

import pytest

from app.channels.gmail.quoted import quoted_messages, quoted_owner_reply, split_quoted

OWNER = frozenset({"harjot@hrre.nl"})
GMAIL_NL = (
    "Dank, donderdag is goed.\n\nGroet, Anouk\n\n"
    "Op ma 3 nov 2026 om 10:12 schreef Harjot Singh <harjot@hrre.nl>:\n\n"
    "> De monteur komt donderdag om 9 uur.\n> Groet, Harjot\n"
)
GMAIL_EN_WRAPPED = (
    "Thanks, that works.\n\nOn Mon, Nov 3, 2026 at 10:12 AM Harjot Singh <\nharjot@hrre.nl> wrote:\n\n"
    "> The plumber comes on Thursday.\n"
)
APPLE_NL = (
    "Prima.\n\nOp 3 nov 2026 om 10:12 heeft Harjot <harjot@hrre.nl> het volgende geschreven:\n\n"
    "﻿De monteur komt donderdag.\n"
)
OUTLOOK_NL = (
    "Akkoord.\n\nVan: Harjot Singh <harjot@hrre.nl>\nVerzonden: maandag 3 november 2026 10:12\n"
    "Aan: Anouk <anouk@example.nl>\nOnderwerp: RE: Lekkage\n\nDe monteur komt donderdag.\n"
)
OUTLOOK_EN = (
    "Agreed.\n\n________________________________\nFrom: Harjot <harjot@hrre.nl>\nSent: Monday, 3 November 2026 10:12\n"
    "To: Anouk\nSubject: RE: Leak\n\nThe plumber comes on Thursday.\n"
)
GERMAN = "Danke.\n\nAm 03.11.2026 um 10:12 schrieb Harjot <harjot@hrre.nl>:\n> Der Installateur kommt am Donnerstag.\n"
FORWARD = (
    "---------- Forwarded message ---------\nVan: Bouw BV <info@bouw.nl>\nDate: ma 3 nov 2026 om 10:12\n"
    "Subject: Offerte\nTo: <harjot@hrre.nl>\n\nHierbij onze offerte van EUR 1.180,00.\n"
)


@pytest.mark.parametrize(
    ("text", "new", "in_quoted"),
    [
        (GMAIL_NL, "Dank, donderdag is goed.\n\nGroet, Anouk", "De monteur komt donderdag om 9 uur."),
        (GMAIL_EN_WRAPPED, "Thanks, that works.", "The plumber comes on Thursday."),
        (APPLE_NL, "Prima.", "De monteur komt donderdag."),
        (OUTLOOK_NL, "Akkoord.", "De monteur komt donderdag."),
        (OUTLOOK_EN, "Agreed.", "The plumber comes on Thursday."),
        (GERMAN, "Danke.", "Der Installateur kommt am Donnerstag."),
    ],
    ids=["gmail-nl", "gmail-en-wrapped", "apple-nl", "outlook-nl", "outlook-en", "german"],
)
def test_split_quoted_separates_the_new_part(text: str, new: str, in_quoted: str) -> None:
    got_new, got_quoted = split_quoted(text)
    assert got_new == new
    assert in_quoted in got_quoted
    assert in_quoted not in got_new


def test_split_quoted_without_a_quote_returns_the_whole_mail() -> None:
    assert split_quoted("Van maandag tot vrijdag ben ik thuis.\nBel mij.") == (
        "Van maandag tot vrijdag ben ik thuis.\nBel mij.",
        "",
    )


def test_split_quoted_keeps_a_forwarded_mail_as_the_new_part() -> None:
    """A forward carries the sender's own words: they are the message, not history."""
    new, quoted = split_quoted(FORWARD)
    assert "Hierbij onze offerte van EUR 1.180,00." in new
    assert quoted == ""


def test_split_quoted_cuts_the_history_below_a_forwarded_mail() -> None:
    new, quoted = split_quoted(FORWARD + "\n" + GMAIL_NL.split("\n\n", 2)[2])
    assert "Hierbij onze offerte" in new
    assert "De monteur komt donderdag" in quoted


def test_split_quoted_does_not_cut_on_a_sentence_that_looks_like_a_header() -> None:
    text = "Van: de week bel ik u.\nOp dinsdag schreef ik u al een brief.\nMet vriendelijke groet"
    assert split_quoted(text) == (text, "")


@pytest.mark.parametrize("text", [GMAIL_NL, GMAIL_EN_WRAPPED, APPLE_NL, OUTLOOK_NL, OUTLOOK_EN, GERMAN])
def test_quoted_owner_reply_finds_harjots_quoted_answer(text: str) -> None:
    assert quoted_owner_reply(text, OWNER)
    assert not quoted_owner_reply(text, frozenset({"someone@else.nl"}))


def test_quoted_owner_reply_is_false_for_a_forward_to_the_owner_and_for_his_address_in_prose() -> None:
    assert not quoted_owner_reply(FORWARD, OWNER)
    assert not quoted_owner_reply("Ik mailde harjot@hrre.nl vorige week.", OWNER)


def test_quoted_messages_name_each_author_newest_first() -> None:
    text = (
        "Ok.\n\nOp 4 nov 2026 om 09:00 schreef Harjot <harjot@hrre.nl>:\n> Donderdag.\n>\n"
        "> Op 3 nov 2026 om 10:00 schreef Anouk <anouk@example.nl>:\n>> Wanneer komt de monteur?\n"
    )
    assert [(m.author, m.text) for m in quoted_messages(text)] == [
        ("harjot@hrre.nl", "Donderdag."),
        ("anouk@example.nl", "Wanneer komt de monteur?"),
    ]


def test_a_story_about_a_date_is_not_an_attribution() -> None:
    text = "Op 3 november was de monteur hier.\nHij keek naar de ketel.\nIn zijn rapport schreef hij:\nketel vervangen."
    assert split_quoted(text) == (text, "")


def test_hostile_text_is_split_quickly() -> None:
    start = time.perf_counter()
    for text in ("Op 1 " + "schreef " * 40_000, ("On 1\n" * 40_000), "Van: x\n" * 40_000, ">" * 200_000):
        split_quoted(text)
    assert time.perf_counter() - start < 5


def test_many_lines_of_hostile_attributions_split_quickly() -> None:
    text = "\n".join("Op 1 " + "schreef " * 36 for _ in range(1_500))
    start = time.perf_counter()
    split_quoted(text)
    assert time.perf_counter() - start < 1.5


@pytest.mark.parametrize(
    ("lead", "attribution"),
    [
        ("Op 3 november is de lekkage begonnen.", "Op 4 nov 2026 om 10:12 schreef Harjot <h@x.nl>:"),
        ("On 3 March the plumber came.", "On Mon, Mar 4, 2026 at 10:12 Harjot <h@x.nl> wrote:"),
    ],
)
def test_a_sentence_starting_with_a_date_above_the_attribution_stays_in_the_new_part(
    lead: str, attribution: str
) -> None:
    new, quoted = split_quoted(f"Beste Harjot,\n\n{lead}\n\n{attribution}\n> Eerder bericht.\n")
    assert new == f"Beste Harjot,\n\n{lead}"
    assert quoted.startswith(attribution)
