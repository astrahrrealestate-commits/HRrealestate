"""The short time labels the inbox shows ("Today 09:30"): the company's local clock, 24 h, local day boundaries."""

from datetime import UTC, datetime
from zoneinfo import ZoneInfo

WEEK_DAYS = 7


def when_label(at: datetime, now: datetime, tz: ZoneInfo, *, weekdays: bool = False) -> str:
    """`Today HH:MM`, `Yesterday HH:MM`, optionally `Sat HH:MM` inside a week, else `DD Mon HH:MM`."""
    local = (at if at.tzinfo else at.replace(tzinfo=UTC)).astimezone(tz)
    days = (now.astimezone(tz).date() - local.date()).days
    clock = local.strftime("%H:%M")
    if days == 0:
        return f"Today {clock}"
    if days == 1:
        return f"Yesterday {clock}"
    if weekdays and days < WEEK_DAYS:
        return f"{local.strftime('%a')} {clock}"
    return local.strftime("%d %b %H:%M")
