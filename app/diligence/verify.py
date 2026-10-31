"""Quote verification: the model's claims and flags are used only when their words are in the document text."""

import re
import unicodedata

from app.contracts.diligence import DDDocRead

_SPACES = re.compile(r"\s+")
_QUOTES = str.maketrans({"‘": "'", "’": "'", "“": '"', "”": '"', "–": "-", "—": "-"})


def normalise(text: str) -> str:
    folded = unicodedata.normalize("NFKC", text).translate(_QUOTES).casefold()
    return _SPACES.sub(" ", folded).strip()


def verify_read(read: DDDocRead, text: str) -> tuple[DDDocRead, int]:
    """The read without the claims and flags whose quote is not in `text`, and how many were dropped."""
    haystack = normalise(text)

    def found(quote: str) -> bool:
        needle = normalise(quote)
        return bool(needle) and needle in haystack

    claims = [c for c in read.claims if found(c.quote)]
    flags = [f for f in read.flags if found(f.quote)]
    dropped = (len(read.claims) - len(claims)) + (len(read.flags) - len(flags))
    return read.model_copy(update={"claims": claims, "flags": flags}), dropped
