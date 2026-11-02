"""Verification of the model's output against the document text. A claim or flag is used only when its quote is in the
text and the quote supports the value; a kind nothing in the text supports is not trusted."""

import re
import unicodedata

from app.contracts.diligence import FIELD_KIND, KIND_KEYWORDS, DDClaim, DDDocRead, DDField, ValueKind

_SPACES = re.compile(r"\s+")
_NON_DIGITS = re.compile(r"\D")
_QUOTES = str.maketrans({"‘": "'", "’": "'", "“": '"', "”": '"', "–": "-", "—": "-"})
MIN_QUOTE_CHARS = 4  # a quote shorter than this proves nothing
UNSUPPORTED_KIND_CONFIDENCE = 0.4  # below the framework's reading threshold: the kind is shown as unclear


def normalise(text: str) -> str:
    folded = unicodedata.normalize("NFKC", text).translate(_QUOTES).casefold()
    return _SPACES.sub(" ", folded).strip()


def _supports(claim: DDClaim, quote: str) -> bool:
    """The value the claim states is visible in its quote: its digits, its date's year, its letter or words."""
    kind = FIELD_KIND[claim.field]
    if kind is ValueKind.number and claim.number is not None:
        return _NON_DIGITS.sub("", format(claim.number.normalize(), "f")) in _NON_DIGITS.sub("", quote)
    if kind is ValueKind.day and claim.day is not None:
        return str(claim.day.year) in quote
    value = normalise(claim.text or "")
    if claim.field is DDField.asbestos:
        return "asbe" in quote  # the value is the model's present/absent reading of an asbestos statement
    if claim.field is DDField.energy_label:
        return re.search(rf"(?<![a-z0-9]){re.escape(value)}(?![a-z0-9])", quote) is not None
    return bool(value) and value in quote


def verify_read(read: DDDocRead, text: str) -> tuple[DDDocRead, int]:
    """The read without the claims and flags that the text does not support, and how many were dropped."""
    haystack = normalise(text)

    def found(quote: str) -> bool:
        needle = normalise(quote)
        return len(needle) >= MIN_QUOTE_CHARS and needle in haystack

    claims = [c for c in read.claims if found(c.quote) and _supports(c, normalise(c.quote))]
    flags = [f for f in read.flags if found(f.quote)]
    dropped = (len(read.claims) - len(claims)) + (len(read.flags) - len(flags))
    update: dict[str, object] = {"claims": claims, "flags": flags}
    words = KIND_KEYWORDS.get(read.doc_kind)
    if words is not None and not any(w in haystack for w in words):
        update["confidence"] = min(read.confidence, UNSUPPORTED_KIND_CONFIDENCE)
    return read.model_copy(update=update), dropped
