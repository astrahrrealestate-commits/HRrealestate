"""What a Super Agent conversation is "about": set by what was discussed, never guessed from the portfolio."""

from collections.abc import Mapping
from typing import Any

# preview-card field -> focus_state key
_FROM_CARD = {
    "caseId": "case_id",
    "unitLabel": "unit_label",
    "recipient": "recipient",
    "contractor": "contractor",
    "actionId": "last_action_id",
    "channel": "channel",
}

NEW_CHAT_FACT = (
    "This is a new conversation: the owner has said nothing earlier in it. The cases listed here are portfolio data, "
    "not something the owner told you, so never say they mentioned a property, tenant or ticket unless it is in the "
    "conversation history."
)


def next_focus(current: Mapping[str, Any], card: Mapping[str, Any] | None) -> dict[str, Any]:
    """The focus after a turn: the old one plus whatever the turn's preview card names. No card, no change."""
    focus = dict(current)
    if card:
        for field, key in _FROM_CARD.items():
            if card.get(field):
                focus[key] = str(card[field])
    return focus


def new_chat_fact(prior_turns: int) -> str:
    """A line for the agent's context when nothing has been said in this conversation yet."""
    return NEW_CHAT_FACT if prior_turns == 0 else ""
