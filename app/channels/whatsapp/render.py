"""Render channel-neutral OwnerMessage to WhatsApp JSON payloads."""

from typing import Any

from app.channels.whatsapp import payloads
from app.contracts import OwnerMessage


def render_whatsapp(msg: OwnerMessage, to: str) -> dict[str, Any]:
    if not msg.choices:
        return payloads.text(to, msg.text)

    if len(msg.choices) <= 3 and not msg.menu_title:
        items = [payloads.Button(c.id, c.label) for c in msg.choices]
        return payloads.buttons(to, msg.text[: payloads.BODY_MAX], items)

    rows = [payloads.ListRow(c.id, c.label, c.description) for c in msg.choices]
    section_title = msg.menu_title or "Options"
    return payloads.list_menu(
        to,
        msg.text[: payloads.BODY_MAX],
        msg.menu_button,
        [payloads.ListSection(section_title, rows[:10])],
    )
