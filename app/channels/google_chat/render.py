"""Render channel-neutral OwnerMessage to Google Chat cardsV2 or text payloads."""

from typing import Any

from app.contracts import OwnerMessage


def render_google_chat(msg: OwnerMessage) -> dict[str, Any]:
    """Renders OwnerMessage into Google Chat API message payload.

    Messages without choices render as plain text. Messages with choices render
    as cardsV2 with textParagraph and interactive buttonList widgets.
    """
    if not msg.choices:
        return {"text": msg.text}

    buttons = []
    for choice in msg.choices:
        button = {
            "text": choice.label,
            "onClick": {
                "action": {
                    "function": "owner_action",
                    "parameters": [{"key": "button_id", "value": choice.id}],
                }
            },
        }
        buttons.append(button)

    section_widgets: list[dict[str, Any]] = [
        {"textParagraph": {"text": msg.text}},
        {"buttonList": {"buttons": buttons}},
    ]

    card: dict[str, Any] = {
        "sections": [{"widgets": section_widgets}],
    }
    if msg.header:
        card["header"] = {"title": msg.header}

    return {
        "cardsV2": [
            {
                "cardId": "estateos_card",
                "card": card,
            }
        ]
    }
