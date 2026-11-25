"""The WhatsApp customer-service window rule, shared by the sender and the chats read side.

Free-form WhatsApp is allowed within 24 h of the other party's last message; we use 23 h for margin. Lives in core
because the pipeline and the sender are sibling layers that may not import each other.
"""

from datetime import datetime, timedelta

WINDOW = timedelta(hours=23)


def window_open(received_at: datetime, now: datetime) -> bool:
    """Open while `received_at` is newer than `now - WINDOW`; exactly at the boundary is closed."""
    return received_at > now - WINDOW


def window_closes_at(received_at: datetime) -> datetime:
    return received_at + WINDOW
