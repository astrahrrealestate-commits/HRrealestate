"""Redaction for logs (structlog processor) and error reports (Sentry deny list).

Three kinds of keys are replaced by `[redacted]`, at any depth and case-insensitively: credentials (the BRIXX
`Authorization` header, tokens), BRIXX personal columns (`ZOEKID`, names, contact data) and row payloads (`row`,
`rows`, ...), so a mirrored BRIXX row can never be logged by accident. `Bearer <token>` inside a string is masked too.
Table names, page numbers, counts and error class names stay readable.
"""

import logging
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
_CHAT_PATH = re.compile(r"(/api/chats/)[^/?#\s\"']+")  # the chat key of /api/chats/{chat_key}/... is a phone number
CHAT_KEY_MASK = "{chat_key}"
_MAX_DEPTH = 8


def mask_chat_paths(text: str) -> str:
    """`/api/chats/+31612345678/messages` -> `/api/chats/{chat_key}/messages`: a contact's number is personal data."""
    return _CHAT_PATH.sub(rf"\1{CHAT_KEY_MASK}", text)


def _scrub(value: Any, depth: int) -> Any:
    if depth > _MAX_DEPTH:
        return REDACTED
    if isinstance(value, str):
        return mask_chat_paths(_BEARER.sub(f"Bearer {REDACTED}", value))
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


def scrub_chat_paths(value: Any, depth: int = 0) -> Any:
    """Mask chat keys in every string of a Sentry event or breadcrumb (URLs, transaction names, messages, data)."""
    if depth > _MAX_DEPTH:
        return value
    if isinstance(value, str):
        return mask_chat_paths(value)
    if isinstance(value, dict):
        return {key: scrub_chat_paths(item, depth + 1) for key, item in value.items()}
    if isinstance(value, list):
        return [scrub_chat_paths(item, depth + 1) for item in value]
    return value


def sentry_before_send(event: Any, _hint: Any) -> Any:
    return scrub_chat_paths(event)


def sentry_before_breadcrumb(crumb: Any, _hint: Any) -> Any:
    return scrub_chat_paths(crumb)


class ChatPathFilter(logging.Filter):
    """Masks the chat key in uvicorn's access line (`POST /api/chats/+316.../messages HTTP/1.1`)."""

    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.args, tuple):
            record.args = tuple(mask_chat_paths(a) if isinstance(a, str) else a for a in record.args)
        return True
