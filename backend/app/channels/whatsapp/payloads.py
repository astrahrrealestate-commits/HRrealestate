"""Pure builders for WhatsApp Cloud API message bodies (identical for Meta direct and 360dialog).

Limits follow the documented Cloud API constraints; violations raise ValueError before anything is sent.
"""

import re
from dataclasses import dataclass
from typing import Any, Literal

_E164 = re.compile(r"\+[1-9][0-9]{6,14}")

TEXT_BODY_MAX = 4096  # plain text messages
BODY_MAX = 1024  # interactive message bodies
BUTTONS_MAX = 3
BUTTON_TITLE_MAX = 20
BUTTON_ID_MAX = 256
LIST_BUTTON_MAX = 20
LIST_ROWS_MAX = 10
LIST_SECTION_TITLE_MAX = 24
LIST_ROW_ID_MAX = 200
LIST_ROW_TITLE_MAX = 24
LIST_ROW_DESCRIPTION_MAX = 72


@dataclass(frozen=True)
class Button:
    id: str
    title: str


@dataclass(frozen=True)
class ListRow:
    id: str
    title: str
    description: str | None = None


@dataclass(frozen=True)
class ListSection:
    title: str
    rows: list[ListRow]


def _check(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def _base(to: str, kind: str, reply_to: str | None) -> dict[str, Any]:
    _check(bool(_E164.fullmatch(to)), f"recipient must be E.164, got {to!r}")
    payload: dict[str, Any] = {
        "messaging_product": "whatsapp",
        "recipient_type": "individual",
        "to": to.removeprefix("+"),
        "type": kind,
    }
    if reply_to:
        payload["context"] = {"message_id": reply_to}
    return payload


def _body(body: str, limit: int = BODY_MAX) -> str:
    _check(0 < len(body) <= limit, f"body must be 1..{limit} characters")
    return body


def text(to: str, body: str, *, reply_to: str | None = None) -> dict[str, Any]:
    payload = _base(to, "text", reply_to)
    payload["text"] = {"body": _body(body, TEXT_BODY_MAX), "preview_url": False}
    return payload


def buttons(to: str, body: str, items: list[Button], *, reply_to: str | None = None) -> dict[str, Any]:
    _check(1 <= len(items) <= BUTTONS_MAX, f"1..{BUTTONS_MAX} buttons")
    _check(len({b.id for b in items}) == len(items), "button ids must be unique")
    for b in items:
        _check(0 < len(b.id) <= BUTTON_ID_MAX, f"button id must be 1..{BUTTON_ID_MAX} characters")
        _check(0 < len(b.title) <= BUTTON_TITLE_MAX, f"button title must be 1..{BUTTON_TITLE_MAX} characters")
    payload = _base(to, "interactive", reply_to)
    payload["interactive"] = {
        "type": "button",
        "body": {"text": _body(body)},
        "action": {"buttons": [{"type": "reply", "reply": {"id": b.id, "title": b.title}} for b in items]},
    }
    return payload


def _row(row: ListRow) -> dict[str, str]:
    _check(0 < len(row.id) <= LIST_ROW_ID_MAX, f"row id must be 1..{LIST_ROW_ID_MAX} characters")
    _check(0 < len(row.title) <= LIST_ROW_TITLE_MAX, f"row title must be 1..{LIST_ROW_TITLE_MAX} characters")
    out = {"id": row.id, "title": row.title}
    if row.description:
        _check(len(row.description) <= LIST_ROW_DESCRIPTION_MAX, "row description too long")
        out["description"] = row.description
    return out


def list_menu(to: str, body: str, button_label: str, sections: list[ListSection]) -> dict[str, Any]:
    _check(0 < len(button_label) <= LIST_BUTTON_MAX, f"list button label must be 1..{LIST_BUTTON_MAX} characters")
    rows = [r for s in sections for r in s.rows]
    _check(1 <= len(rows) <= LIST_ROWS_MAX, f"1..{LIST_ROWS_MAX} rows in total")
    _check(len({r.id for r in rows}) == len(rows), "row ids must be unique")
    for s in sections:
        _check(0 < len(s.title) <= LIST_SECTION_TITLE_MAX, "section title too long")
        _check(len(s.rows) >= 1, "every section needs at least one row")
    payload = _base(to, "interactive", None)
    payload["interactive"] = {
        "type": "list",
        "body": {"text": _body(body)},
        "action": {
            "button": button_label,
            "sections": [{"title": s.title, "rows": [_row(r) for r in s.rows]} for s in sections],
        },
    }
    return payload


def template(to: str, name: str, language: str, body_params: list[str]) -> dict[str, Any]:
    """Approved template (the only way to open a conversation outside the 24h window, e.g. the 07:30 briefing)."""
    _check(bool(re.fullmatch(r"[a-z0-9_]{1,512}", name)), "template name must be lowercase snake_case")
    for param in body_params:
        # Meta rejects template parameters with newlines, tabs or more than 4 consecutive spaces (error 132018).
        _check(bool(param) and not re.search(r"[\n\t]| {5,}", param), f"invalid template parameter {param[:30]!r}")
    payload = _base(to, "template", None)
    payload["template"] = {"name": name, "language": {"code": language}}
    if body_params:
        payload["template"]["components"] = [
            {"type": "body", "parameters": [{"type": "text", "text": p} for p in body_params]}
        ]
    return payload


def media(
    to: str,
    *,
    kind: Literal["image", "document"],
    link: str,
    filename: str | None = None,
    caption: str | None = None,
) -> dict[str, Any]:
    """Outbound WhatsApp `image` or `document` message referencing an HTTPS URL."""
    _check(link.startswith("https://"), "WhatsApp media link must use https://")
    payload = _base(to, kind, None)
    body: dict[str, Any] = {"link": link}
    if kind == "document" and filename:
        body["filename"] = filename[:240]
    if caption and caption.strip():
        body["caption"] = caption.strip()[:BODY_MAX]
    payload[kind] = body
    return payload
