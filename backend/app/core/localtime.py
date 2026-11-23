"""Dutch time. Every time a person reads is Europe/Amsterdam wall-clock time, never UTC or the server's zone."""

from datetime import UTC, datetime
from zoneinfo import ZoneInfo

AMSTERDAM = ZoneInfo("Europe/Amsterdam")


def to_local(moment: datetime) -> datetime:
    """`moment` in Dutch time. A naive value is read as UTC, which is how every timestamp is stored."""
    return (moment if moment.tzinfo else moment.replace(tzinfo=UTC)).astimezone(AMSTERDAM)
