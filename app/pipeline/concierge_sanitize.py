"""Untrusted concierge `text` (task titles, clarify questions, durations): strip links, contact and bank details and
amounts before the text reaches the owner (CLAUDE.md invariant 6).

Dates and clock times (the draft output guard's patterns) are kept; any other run of 8+ digits is redacted.
Known gaps (best effort): bare domains without `www.`/scheme (`evil.example/login`), numbers spelled out in words.
"""

import re
import unicodedata

from app.pipeline.output_guard import DATE, DOTTED_TIME, URL

MAX_TEXT = 400
REDACTED = "[redacted]"
GENERIC_QUESTION = "Could you tell me a bit more about what you need?"

_EMAIL = re.compile(r"\S+@\S+")
_OBFUSCATED_EMAIL = re.compile(r"\S+\s*[\[(]\s*at\s*[\])]\s*\S+(?:\s*[\[(]\s*dot\s*[\])]\s*\S+)+", re.IGNORECASE)
_IBAN = re.compile(r"[A-Z]{2}\d{2}[A-Z0-9]{10,30}", re.IGNORECASE)
_SPACED_IBAN = re.compile(r"[A-Z]{2}\d{2}(?: [A-Z0-9]{4}){2,7}(?: [A-Z0-9]{1,4})?", re.IGNORECASE)
_NUM = r"\d[\d.,]*(?: \d{3}(?!\d)[\d.,]*)*"  # 950 · 1.200,50 · 1 200
_AMOUNT = re.compile(
    rf"(?:[€$£]|(?<![a-z])(?:EUR|USD|GBP))\s?-?{_NUM}|{_NUM}\s?(?:[€$£]|(?:EUR|USD|GBP|euros?)(?![a-z]))",
    re.IGNORECASE,
)
_HOLD, _SLOT = 0xE000, 0xE100  # private-use marks for kept dates; `_normalise` drops private-use input characters
_PHONE = re.compile(r"\+?\d(?:[\s()./+--]*\d){7,}")  # 8+ digits; a held date never splits a run
_RESTORE = re.compile("([-])")


def _normalise(text: str) -> str:
    """Control characters become spaces, format and private-use characters vanish, whitespace collapses."""
    kept = []
    for ch in text:
        cat = unicodedata.category(ch)
        if cat == "Cc":
            kept.append(" ")
        elif cat not in ("Cf", "Co"):
            kept.append(ch)
    return " ".join("".join(kept).split())


def _spaced_iban(match: re.Match[str]) -> str:
    """Spaced groups only count as an IBAN when they carry an account number (8+ digits), not ordinary words."""
    return REDACTED if sum(ch.isdigit() for ch in match.group(0)) >= 8 else match.group(0)


def _redact_phones(text: str) -> str:
    kept: list[str] = []

    def hold(match: re.Match[str]) -> str:
        kept.append(match.group(0))
        return chr(_HOLD) + chr(_SLOT + len(kept) - 1)

    held = DATE.sub(hold, DOTTED_TIME.sub(hold, text))  # same order as the draft output guard
    redacted = _PHONE.sub(REDACTED, held)
    return _RESTORE.sub(lambda m: kept[ord(m.group(1)) - _SLOT], redacted)


def redact(text: str) -> str:
    for pattern in (URL, _EMAIL, _OBFUSCATED_EMAIL, _IBAN):  # links and emails first: they may hold digits
        text = pattern.sub(REDACTED, text)
    text = _AMOUNT.sub(REDACTED, _SPACED_IBAN.sub(_spaced_iban, text))
    return _redact_phones(text)


def has_contact_details(text: str) -> bool:
    """An `@` or a run of 8+ digits (dates and clock times excepted): what a plan's text must never carry.

    For free text only, not ids: a UUID's dash-separated digits can trip it. Skip id-shaped values before calling.
    """
    return "@" in text or _redact_phones(text) != text


def sanitize(text: str) -> str:
    """Normalised, redacted and bounded: safe to store as a title or to show to the owner."""
    return redact(_normalise(text))[:MAX_TEXT]


def safe_question(text: str) -> str:
    """A clarify question is shown verbatim only when nothing had to be redacted; otherwise a fixed phrase."""
    plain = _normalise(text)
    if not plain or redact(plain) != plain:
        return GENERIC_QUESTION
    return plain[:MAX_TEXT]


def normalise_query(text: str) -> str:
    """The owner's search terms, normalised and bounded. Not redacted: it is a bound, company-scoped parameter."""
    return _normalise(text)[:MAX_TEXT]
