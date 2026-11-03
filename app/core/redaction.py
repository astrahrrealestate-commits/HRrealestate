"""Redaction for logs (structlog processor) and error reports (Sentry deny list).

Three kinds of keys are replaced by `[redacted]`, at any depth and case-insensitively: credentials (the BRIXX
`Authorization` header, tokens), BRIXX personal columns (`ZOEKID`, names, contact data) and row payloads (`row`,
`rows`, ...), so a mirrored BRIXX row can never be logged by accident. `Bearer <token>` inside a string is masked too.
Table names, page numbers, counts and error class names stay readable.
"""

import re
from collections.abc import MutableMapping
from typing import Any

from sentry_sdk.scrubber import DEFAULT_DENYLIST

REDACTED = "[redacted]"

SECRET_KEYS = frozenset(
    {"authorization", "proxy-authorization", "token", "access_token", "refresh_token", "brixx_token", "api_key"}
)
# BRIXX PRG_RELATIE personal columns (ZOEKID = last 3 BSN digits + birth date + surname initial, API doc p. 7)
PERSONAL_KEYS = frozenset(
    {
        "zoekid",
        "weergavenaam",
        "weergavenaam2",
        "organisatienm",
        "achternaam",
        "voornaam",
        "voorletters",
        "geboortedatum",
        "email",
        "emailadres",
        "telefoonnr",
        "mobielnr",
        "iban",
    }
)
ROW_KEYS = frozenset({"row", "rows", "record", "records", "row_values"})
_DENIED = SECRET_KEYS | PERSONAL_KEYS
_BEARER = re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/=-]+")
_MAX_DEPTH = 8


def _scrub(value: Any, depth: int) -> Any:
    if depth > _MAX_DEPTH:
        return REDACTED
    if isinstance(value, str):
        return _BEARER.sub(f"Bearer {REDACTED}", value)
    if isinstance(value, MutableMapping):
        return {key: _scrub_item(key, item, depth) for key, item in value.items()}
    if isinstance(value, list | tuple):
        return [_scrub(item, depth + 1) for item in value]
    return value


def _scrub_item(key: object, value: Any, depth: int) -> Any:
    lowered = key.lower() if isinstance(key, str) else key
    if lowered in _DENIED or lowered in ROW_KEYS:
        return REDACTED
    return _scrub(value, depth + 1)


def redact_event(_logger: object, _method: str, event_dict: MutableMapping[str, Any]) -> MutableMapping[str, Any]:
    """structlog processor: redact before rendering; the `event` name itself is never touched."""
    for key in list(event_dict):
        if key != "event":
            event_dict[key] = _scrub_item(key, event_dict[key], 0)
    return event_dict


def sentry_denylist() -> list[str]:
    """Sentry's default deny list plus the same keys the log processor redacts."""
    return [*DEFAULT_DENYLIST, *sorted(_DENIED | ROW_KEYS)]
