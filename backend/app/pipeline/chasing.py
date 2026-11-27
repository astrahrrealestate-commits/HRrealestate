"""Follow-up ladder (#5), pure: when a wait is due, chase (up to `escalate_after_chases` times), then escalate."""

from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from enum import StrEnum
from zoneinfo import ZoneInfo

from app.db.enums import WaitStatus

DEFAULT_TZ = "Europe/Amsterdam"
OVERDUE_HOUR = 9  # 09:00 local time the morning after a promised date


class ChaseStep(StrEnum):
    none = "none"
    chase = "chase"
    escalate = "escalate"


@dataclass(frozen=True)
class ChasePolicy:
    chase_after_days: int = 3
    escalate_after_chases: int = 2


def add_business_days(start: datetime, days: int, tz: str) -> datetime:
    """Same local wall time `days` working days later (Sat/Sun skipped; a weekend start counts from Monday)."""
    local = start.astimezone(ZoneInfo(tz))
    day = local.date()
    remaining = days
    while remaining > 0 or day.weekday() >= 5:
        day += timedelta(days=1)
        if day.weekday() < 5:
            remaining -= 1
    wall = datetime.combine(day, local.timetz().replace(tzinfo=None), tzinfo=ZoneInfo(tz))
    return wall.astimezone(UTC)


def next_morning_after(promised_date: date, tz: str = DEFAULT_TZ, hour: int = OVERDUE_HOUR) -> datetime:
    """09:00 local time on the morning after `promised_date` (e.g. promised Tuesday -> due Wednesday 09:00)."""
    zone = ZoneInfo(tz)
    wall = datetime.combine(promised_date + timedelta(days=1), time(hour, 0), tzinfo=zone)
    return wall.astimezone(UTC)


def overdue_days_from(expected_by: datetime, now: datetime, tz: str = DEFAULT_TZ) -> int:
    """Whole overdue days once `now >= expected_by` (returns 1 on the first overdue morning, 0 when on track)."""
    if now < expected_by:
        return 0
    zone = ZoneInfo(tz)
    due_day = expected_by.astimezone(zone).date()
    cur_day = now.astimezone(zone).date()
    return max(1, (cur_day - due_day).days + 1)


def next_step(
    status: WaitStatus, chase_count: int, expected_by: datetime, policy: ChasePolicy, now: datetime
) -> ChaseStep:
    if status is not WaitStatus.waiting or now < expected_by:
        return ChaseStep.none
    return ChaseStep.chase if chase_count < policy.escalate_after_chases else ChaseStep.escalate
