"""Channel-neutral model of messages Harjot receives (cards, briefings, alerts, commands)."""

from dataclasses import dataclass


@dataclass(frozen=True)
class OwnerChoice:
    id: str  # ButtonId string e.g. "apr:<uuid>:d1" or "doc:<uuid>:lease"
    label: str  # "Send draft 1", "Approve", "File as lease"
    description: str | None = None  # short excerpt / description for list menu


@dataclass(frozen=True)
class OwnerMessage:
    text: str
    choices: tuple[OwnerChoice, ...] = ()
    header: str | None = None
    menu_title: str | None = None
    menu_button: str = "Choose"
