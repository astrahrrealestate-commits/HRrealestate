"""String hygiene for email-derived values: Postgres-safe text, single-line headers, safe filenames and MIME types."""

import re

_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_HEADER_SPACE = re.compile(r"[\s\x00-\x1f\x7f]+")
_MIME = re.compile(r"[a-z0-9!#$&^_.+-]+/[a-z0-9!#$&^_.+-]+")
FALLBACK_MIME = "application/octet-stream"


def clean_text(value: str) -> str:
    """Postgres-safe text: lone surrogates → U+FFFD, C0 controls (except \\n, \\t) and NUL removed."""
    value = value.encode("utf-8", "surrogatepass").decode("utf-8", "replace")
    return _CONTROL.sub("", value.replace("\r\n", "\n").replace("\r", "\n"))


def clean_header(value: str | None, limit: int = 998) -> str | None:
    """Single-line header-derived value (no CR/LF injection into drafts or metadata)."""
    if value is None:
        return None
    single = _HEADER_SPACE.sub(" ", clean_text(value)).strip()
    return single[:limit] or None


def clean_filename(value: str | None) -> str | None:
    name = clean_header(value, 255)
    if not name:
        return None
    return re.split(r"[\\/]", name)[-1].strip(". ") or None


def clean_mime(value: str | None) -> str:
    if value is None or _CONTROL.search(value) or not value.isascii():
        return FALLBACK_MIME  # a MIME type with control or 8-bit characters is hostile, not repairable
    candidate = (clean_header(value, 255) or "").lower()
    return candidate if _MIME.fullmatch(candidate) else FALLBACK_MIME
