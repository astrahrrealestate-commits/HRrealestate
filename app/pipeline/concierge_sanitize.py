"""Untrusted concierge `text` (task titles, clarify questions, search queries, durations): strip contact and bank
details and amounts before the text reaches a DB query or the owner (CLAUDE.md invariant 6)."""

import re
import unicodedata

MAX_TEXT = 400
REDACTED = "[redacted]"
GENERIC_QUESTION = "Could you tell me a bit more about what you need?"

_EMAIL = re.compile(r"\S+@\S+")
_IBAN = re.compile(r"[A-Z]{2}\d{2}[A-Z0-9]{10,30}|[A-Z]{2}\d{2}(?: [A-Z0-9]{4}){2,7}(?: [A-Z0-9]{1,4})?")
_AMOUNT = re.compile(
    r"(?:[€$£]|(?<![a-z])(?:EUR|USD|GBP))\s?-?\d(?:[\d.,]*\d)?"
    r"|\d(?:[\d.,]*\d)?\s?(?:[€$£]|(?:EUR|USD|GBP|euros?)(?![a-z]))",
    re.IGNORECASE,
)
_PHONE = re.compile(r"\+?\d(?:[\s().+-]*\d){7,}")  # 8+ digits, separators allowed: phones, account numbers
_PATTERNS = (_EMAIL, _IBAN, _AMOUNT, _PHONE)  # emails first: they may hold digits


def _normalise(text: str) -> str:
    """Control characters become spaces, format characters (zero-width etc.) vanish, whitespace collapses."""
    kept = []
    for ch in text:
        cat = unicodedata.category(ch)
        if cat == "Cc":
            kept.append(" ")
        elif cat != "Cf":
            kept.append(ch)
    return " ".join("".join(kept).split())


def redact(text: str) -> str:
    for pattern in _PATTERNS:
        text = pattern.sub(REDACTED, text)
    return text


def sanitize(text: str) -> str:
    """Normalised, redacted and bounded: safe to store as a title or to show to the owner."""
    return redact(_normalise(text))[:MAX_TEXT]


def safe_question(text: str) -> str:
    """A clarify question is shown verbatim only when nothing had to be redacted; otherwise a fixed phrase."""
    plain = _normalise(text)
    if not plain or redact(plain) != plain:
        return GENERIC_QUESTION
    return plain[:MAX_TEXT]


def clean_query(text: str) -> str:
    """Search terms without redacted parts, with LIKE wildcards escaped (escape character `\\`)."""
    terms = " ".join(sanitize(text).replace(REDACTED, " ").split())
    return terms.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
