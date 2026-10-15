"""Render a channel-neutral OwnerMessage to the JSON the dashboard feed stores and the SPA shows."""

from typing import Any

from app.contracts import OwnerMessage


def to_payload(message: OwnerMessage) -> dict[str, Any]:
    """`{"text", "header", "choices": [{"id","label","description"}], "menu_title"}`. Choice ids stay `ButtonId`
    strings (`apr:<uuid>:d1`); the SPA calls `POST /approvals/{id}/decide` with the suffix."""
    return {
        "text": message.text,
        "header": message.header,
        "choices": [{"id": c.id, "label": c.label, "description": c.description} for c in message.choices],
        "menu_title": message.menu_title,
    }
