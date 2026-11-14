"""Follow-up ladder (#5), pure: when a wait is due, chase (up to `escalate_after_chases` times), then escalate."""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from zoneinfo import ZoneInfo

from app.db.enums import WaitStatus


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


def next_step(
    status: WaitStatus, chase_count: int, expected_by: datetime, policy: ChasePolicy, now: datetime
) -> ChaseStep:
    if status is not WaitStatus.waiting or now < expected_by:
        return ChaseStep.none
    return ChaseStep.chase if chase_count < policy.escalate_after_chases else ChaseStep.escalate
