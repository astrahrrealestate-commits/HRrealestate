"""Concierge sanitiser: model `text` never carries links, contact details, bank details or amounts to the owner."""

import re

import pytest
from hypothesis import given
from hypothesis import strategies as st

from app.pipeline.concierge_sanitize import (
    GENERIC_QUESTION,
    MAX_TEXT,
    REDACTED,
    normalise_query,
    redact,
    safe_question,
    sanitize,
)
from app.pipeline.output_guard import DATE, DOTTED_TIME

_EMAIL = re.compile(r"\S+@\S+")
_URL = re.compile(r"(?:https?://|www\.)\S+", re.IGNORECASE)
_DIGITS8 = re.compile(r"\d(?:[\s()./+-]*\d){7,}")
_IBAN = re.compile(r"[A-Z]{2}\d{2}[A-Z0-9]{10,30}", re.IGNORECASE)
_AMOUNT = re.compile(r"[€$£]\s?\d")

emails = st.from_regex(r"[a-z0-9._%+-]{1,12}@[a-z0-9-]{1,10}\.[a-z]{2,4}", fullmatch=True)
urls = st.from_regex(r"(https?://|www\.)[a-z0-9-]{1,12}\.[a-z]{2,4}(/[a-z0-9]{0,8})?", fullmatch=True)
phones = st.from_regex(r"\+?[0-9]{2}[ /-]?[0-9]{3}[ /-]?[0-9]{3}[ /-]?[0-9]{2,4}", fullmatch=True)
ibans = st.from_regex(r"[A-Za-z]{2}[0-9]{2}[A-Za-z]{4}[0-9]{10}", fullmatch=True)
amounts = st.from_regex(r"(€ ?[0-9]{1,5}([.,][0-9]{2})?|[0-9]{1,5},[0-9]{2} ?EUR)", fullmatch=True)
words = st.text(alphabet=st.characters(categories=("L", "Zs", "P")), max_size=40)


def _clean(out: str) -> None:
    assert not _EMAIL.search(out)
    assert not _URL.search(out)
    assert not _DIGITS8.search(DATE.sub(" ", DOTTED_TIME.sub(" ", out)))  # dates and times are kept
    assert not _IBAN.search(out)
    assert not _AMOUNT.search(out)


@given(st.text(max_size=500))
def test_any_text_comes_out_clean_and_bounded(raw: str) -> None:
    out = sanitize(raw)
    _clean(out)
    assert len(out) <= MAX_TEXT


@given(st.text(max_size=300))
def test_sanitize_is_idempotent(raw: str) -> None:
    once = sanitize(raw)
    assert sanitize(once) == once


@given(words, st.one_of(emails, urls, phones, ibans, amounts), words)
def test_planted_secret_is_removed(before: str, secret: str, after: str) -> None:
    out = sanitize(f"{before} {secret} {after}")
    assert secret not in out
    assert REDACTED in out
    _clean(out)


@given(st.text(alphabet=st.characters(categories=("L", "Zs")), max_size=200))
def test_plain_words_are_kept(raw: str) -> None:
    assert sanitize(raw) == " ".join(raw.split())[:MAX_TEXT]


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("mail jan@example.nl now", f"mail {REDACTED} now"),
        ("mail jan [at] example [dot] nl now", f"mail {REDACTED} now"),
        ("Re-authorise at https://evil.example/login now", f"Re-authorise at {REDACTED} now"),
        ("log in on www.evil.example today", f"log in on {REDACTED} today"),
        ("bel +31 6 1234 5678", f"bel {REDACTED}"),
        ("bel 06/1234/5678", f"bel {REDACTED}"),
        ("IBAN NL91ABNA0417164300 please", f"IBAN {REDACTED} please"),
        ("iban nl91abna0417164300 please", f"iban {REDACTED} please"),
        ("IBAN NL91 ABNA 0417 1643 00 please", f"IBAN {REDACTED} please"),
        ("pay €950,00 today", f"pay {REDACTED} today"),
        ("pay € 1 200 today", f"pay {REDACTED} today"),
        ("pay 950 euro today", f"pay {REDACTED} today"),
        ("inspect boiler on 2026-10-15", "inspect boiler on 2026-10-15"),
        ("inspect boiler on 15-10-2026 at 10:30", "inspect boiler on 15-10-2026 at 10:30"),
        ("call plumber about flat 12", "call plumber about flat 12"),
        ("nr12 deze week langs", "nr12 deze week langs"),
    ],
)
def test_examples(raw: str, expected: str) -> None:
    assert redact(raw) == expected


def test_safe_question_replaces_redacted_output() -> None:
    assert safe_question("Which tenant do you mean?") == "Which tenant do you mean?"
    assert safe_question("Is the visit on 15-10-2026?") == "Is the visit on 15-10-2026?"
    assert safe_question("Send it to jan@example.nl?") == GENERIC_QUESTION
    assert safe_question("Re-authorise at https://evil.example/login now") == GENERIC_QUESTION
    assert safe_question("Check www.evil.example?") == GENERIC_QUESTION
    assert safe_question("   ") == GENERIC_QUESTION


def test_normalise_query_keeps_terms_and_bounds_length() -> None:
    assert normalise_query("  lekkage \n jan@example.nl 100%_x ") == "lekkage jan@example.nl 100%_x"
    assert len(normalise_query("a" * 1000)) == MAX_TEXT
