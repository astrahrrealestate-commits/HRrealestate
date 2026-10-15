"""Concierge sanitiser: model `text` never carries contact details, bank details or amounts to the owner or a query."""

import re

from hypothesis import given
from hypothesis import strategies as st

from app.pipeline.concierge_sanitize import (
    GENERIC_QUESTION,
    MAX_TEXT,
    REDACTED,
    clean_query,
    redact,
    safe_question,
    sanitize,
)

_EMAIL = re.compile(r"\S+@\S+")
_DIGITS8 = re.compile(r"\d(?:[\s().+-]*\d){7,}")
_IBAN = re.compile(r"[A-Z]{2}\d{2}[A-Z0-9]{10,30}")
_AMOUNT = re.compile(r"[€$£]\s?\d")

emails = st.from_regex(r"[a-z0-9._%+-]{1,12}@[a-z0-9-]{1,10}\.[a-z]{2,4}", fullmatch=True)
phones = st.from_regex(r"\+?[0-9]{2}[ -]?[0-9]{3}[ -]?[0-9]{3}[ -]?[0-9]{2,4}", fullmatch=True)
ibans = st.from_regex(r"[A-Z]{2}[0-9]{2}[A-Z]{4}[0-9]{10}", fullmatch=True)
amounts = st.from_regex(r"(€ ?[0-9]{1,5}([.,][0-9]{2})?|[0-9]{1,5},[0-9]{2} ?EUR)", fullmatch=True)
words = st.text(alphabet=st.characters(categories=("L", "Zs", "P")), max_size=40)


def _clean(out: str) -> None:
    assert not _EMAIL.search(out)
    assert not _DIGITS8.search(out)
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


@given(words, st.one_of(emails, phones, ibans, amounts), words)
def test_planted_secret_is_removed(before: str, secret: str, after: str) -> None:
    out = sanitize(f"{before} {secret} {after}")
    assert secret not in out
    assert REDACTED in out
    _clean(out)


@given(st.text(alphabet=st.characters(categories=("L", "Zs")), max_size=200))
def test_plain_words_are_kept(raw: str) -> None:
    assert sanitize(raw) == " ".join(raw.split())[:MAX_TEXT]


def test_examples() -> None:
    assert redact("mail jan@example.nl now") == f"mail {REDACTED} now"
    assert redact("bel +31 6 1234 5678") == f"bel {REDACTED}"
    assert redact("IBAN NL91ABNA0417164300 please") == f"IBAN {REDACTED} please"
    assert redact("pay €950,00 today") == f"pay {REDACTED} today"
    assert redact("pay 950 euro today") == f"pay {REDACTED} today"
    assert redact("call plumber about flat 12") == "call plumber about flat 12"


def test_safe_question_replaces_redacted_output() -> None:
    assert safe_question("Which tenant do you mean?") == "Which tenant do you mean?"
    assert safe_question("Send it to jan@example.nl?") == GENERIC_QUESTION
    assert safe_question("   ") == GENERIC_QUESTION


def test_clean_query_drops_redactions_and_escapes_wildcards() -> None:
    assert clean_query("leak jan@example.nl") == "leak"
    assert clean_query("100%_done\\") == "100\\%\\_done\\\\"
    assert clean_query("+31612345678") == ""
