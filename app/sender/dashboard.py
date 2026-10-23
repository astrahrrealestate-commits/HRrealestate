"""Owner delivery to the dashboard: one idempotent `owner_feed` row. No window, outbox, Send row or provider call."""

from functools import partial
from typing import Any
from uuid import UUID

from sqlalchemy import Engine
from sqlalchemy.orm import Session

from app.channels.dashboard import feed
from app.channels.whatsapp.render import render_whatsapp
from app.contracts import OwnerMessage


def _card_text(payload: dict[str, Any]) -> str | None:
    """Readable text of a Google Chat cardsV2 dict: header title, then textParagraph / decoratedText strings."""
    lines: list[str] = []
    for entry in payload.get("cardsV2") or []:
        card = entry.get("card", {}) if isinstance(entry, dict) else {}
        title = (card.get("header") or {}).get("title")
        if title:
            lines.append(str(title))
        for section in card.get("sections") or []:
            for widget in section.get("widgets") or []:
                for name, field in (("textParagraph", "text"), ("decoratedText", "text")):
                    value = (widget.get(name) or {}).get(field)
                    if value:
                        lines.append(str(value))
    return "\n".join(lines) or None


def _dict_text(payload: dict[str, Any]) -> str:
    """Readable body of a WhatsApp `{"text": {"body"}}`, Chat `{"text"}` / cardsV2 or WhatsApp interactive dict."""
    text = payload.get("text")
    interactive = payload.get("interactive")
    if isinstance(text, dict) and "body" in text:
        return str(text["body"])
    if isinstance(text, str):
        return text
    if isinstance(interactive, dict) and isinstance(interactive.get("body"), dict):
        return str(interactive["body"].get("text", ""))
    return _card_text(payload) or "(no text)"


def resolve_message(build: Any, to: str) -> OwnerMessage:
    """An OwnerMessage when one is available (directly, wrapped by `partial(render_whatsapp, msg)`, or returned by
    the callable); otherwise the `{"text": body}` fallback built from a WhatsApp-style dict."""
    if isinstance(build, OwnerMessage):
        return build
    wrapped = build.args[0] if isinstance(build, partial) and build.func is render_whatsapp and build.args else None
    if isinstance(wrapped, OwnerMessage):
        return wrapped
    result = build(to) if callable(build) else build
    if isinstance(result, OwnerMessage):
        return result
    if isinstance(result, dict):
        return OwnerMessage(text=_dict_text(result))
    return OwnerMessage(text=str(result))


def deliver_dashboard(engine: Engine, company_id: UUID, key: str, build: Any, to: str) -> str:
    with Session(engine) as session:
        delivered = feed.existing(session, company_id, key)
    if delivered is not None:  # a replay: nothing to build, nothing to insert
        return str(delivered)
    kind = feed.kind_for_key(key)
    message = resolve_message(build, to)
    with Session(engine) as session, session.begin():
        row_id = feed.deliver(session, company_id, key, kind, feed.ref_for_key(key, kind), message)
    return str(row_id)
