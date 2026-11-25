"""Forwarded mail: markers and the quoted header block that names the original sender (Gmail, Apple Mail; en/nl/de)."""

import re

from app.channels.text_clean import clean_header

FORWARD_MARKERS = re.compile(
    r"^-{3,}\s*(Forwarded message|Weitergeleitete Nachricht|Original-Nachricht|Doorgestuurd bericht"
    r"|Doorgestuurd e-mailbericht)\s*-{3,}\s*$"
    r"|^(Begin forwarded message|Anfang der weitergeleiteten Nachricht|Begin doorgestuurd bericht):\s*$",
    re.IGNORECASE | re.MULTILINE,
)
_FROM_LINE = re.compile(r"^\s*(?:From|Van|Von)\s*:\s*(?P<value>.+)$", re.IGNORECASE)
_HEADER_LINES = 8  # the quoted header block sits right under the marker
_EMAIL = re.compile(r"[\w.+'-]+@[\w-]+(?:\.[\w-]+)+")


def _from_value(value: str) -> tuple[str, str | None] | None:
    found = _EMAIL.search(value)
    if found is None:
        return None
    name = value[: found.start()].strip().rstrip("<[(").strip().strip("\"'*") or None
    return found.group(0).lower(), clean_header(name) if name else None


def origin_from_text(full_text: str) -> tuple[str, str | None] | None:
    """(address, display name) from the header block under the first forward marker, or None."""
    marker = FORWARD_MARKERS.search(full_text)
    if marker is None:
        return None
    for line in full_text[marker.end() :].split("\n")[: _HEADER_LINES + 1]:
        from_line = _FROM_LINE.match(line)
        if from_line is not None:
            return _from_value(from_line.group("value"))
    return None
