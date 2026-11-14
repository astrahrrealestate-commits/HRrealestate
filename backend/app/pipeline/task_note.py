"""What the Super Agent adds after it puts a task on the owner's list.

A task is a to-do, never an action: nothing is sent, booked or paid by creating one. A title that sounds like an
action must not leave the owner thinking it happened, and an amount in it is removed by the sanitizer (untrusted
text carries no amounts, CLAUDE.md invariant 6), so no budget was recorded or checked against a cap.
"""

import re

from app.pipeline.concierge_sanitize import REDACTED

_OUTBOUND = re.compile(
    r"\b(dispatch|send|sending|book|order|pay|payment|nudge|remind|reminder|contact|call|schedule|approve|"
    r"authori[sz]e|notify|email|whatsapp)\b",
    re.IGNORECASE,
)


def task_note(title: str, ref: str) -> str:
    """Sentences to append to "Task added: <title> #<ref>"."""
    parts: list[str] = []
    if _OUTBOUND.search(title):
        parts.append(
            "This is only a to-do on your list. Nothing was sent, booked or paid; anything that goes to a "
            "contractor or tenant still needs your approval."
        )
    if REDACTED in title:
        parts.append(
            "The amount was not kept (amounts are never stored in task text), so no budget was recorded or checked "
            "against a cap."
        )
    parts.append(f'Say "done #{ref}" to remove it.')
    return " ".join(parts)
