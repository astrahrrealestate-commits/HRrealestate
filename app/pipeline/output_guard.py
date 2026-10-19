"""Draft output guard: a reply must not introduce a link, bank account or phone number that is not in the source
conversation. A model that was talked into inserting an attacker's payment link or number is caught here. Pure."""

import re

URL = re.compile(r"(?:https?://|www\.)\S+", re.IGNORECASE)
_IBAN = re.compile(r"\b[A-Z]{2}\d{2}(?:\s?[A-Z0-9]{4}){2,7}(?:\s?[A-Z0-9]{1,4})?\b")
_PHONE = re.compile(r"(?<!\w)\+?\d[\d\s().-]{7,}\d")
_TIME = r"(?:[ T]\d{1,2}:\d{2})?(?!\d|[\s-]\d)"
DATE = re.compile(rf"(?<!\d[-./ ])\b(?:\d{{1,2}}[-./ ]\d{{1,2}}[-./ ]\d{{2,4}}|\d{{4}}-\d{{1,2}}-\d{{1,2}}){_TIME}")
DOTTED_TIME = re.compile(r"(?<![\d.])\d{1,2}[.:]\d{2}(?![\d.])")
_NOISE = re.compile(r"[\s().,;:!?-]")


def _norm(value: str) -> str:
    return _NOISE.sub("", value).lower()


def unverified(draft: str, source: str) -> list[str]:
    """Links, IBANs and phone numbers in `draft` that do not appear (ignoring spacing/punctuation) in `source`.

    An item contained in a longer found item (an IBAN's digit groups also look like a phone number) is dropped.
    """
    known = _norm(source)
    no_dates = DATE.sub(" ", DOTTED_TIME.sub(" ", draft))
    found = {_norm(m) for pattern in (URL, _IBAN) for m in pattern.findall(draft)}
    found |= {_norm(m) for m in _PHONE.findall(no_dates)}
    new = {item for item in found if item and item not in known}
    return sorted(item for item in new if not any(item != other and item in other for other in new))
