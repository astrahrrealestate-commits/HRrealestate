from datetime import UTC, datetime, timedelta

import pytest

from app.db.enums import WaitStatus
from app.pipeline.chasing import ChasePolicy, ChaseStep, add_business_days, next_step

AMS = "Europe/Amsterdam"
POLICY = ChasePolicy(chase_after_days=3, escalate_after_chases=2)


@pytest.mark.parametrize(
    ("start", "days", "expected"),
    [
        (datetime(2026, 10, 5, 8, 0, tzinfo=UTC), 3, datetime(2026, 10, 8, 8, 0, tzinfo=UTC)),  # Mon → Thu
        (datetime(2026, 10, 8, 8, 0, tzinfo=UTC), 3, datetime(2026, 10, 13, 8, 0, tzinfo=UTC)),  # Thu → Tue
        (datetime(2026, 10, 10, 8, 0, tzinfo=UTC), 1, datetime(2026, 10, 12, 8, 0, tzinfo=UTC)),  # Sat → Mon
        # 23 Oct 2026 (Fri) + 3 business days crosses the DST change on 25 Oct: same local 10:00, one hour later UTC
        (datetime(2026, 10, 23, 8, 0, tzinfo=UTC), 3, datetime(2026, 10, 28, 9, 0, tzinfo=UTC)),
    ],
)
def test_add_business_days_keeps_local_wall_time(start: datetime, days: int, expected: datetime) -> None:
    assert add_business_days(start, days, AMS) == expected


NOW = datetime(2026, 10, 7, 9, 0, tzinfo=UTC)


@pytest.mark.parametrize(
    ("status", "chases", "due", "expected"),
    [
        (WaitStatus.waiting, 0, NOW + timedelta(hours=1), ChaseStep.none),  # not due yet
        (WaitStatus.waiting, 0, NOW, ChaseStep.chase),
        (WaitStatus.waiting, 1, NOW - timedelta(days=1), ChaseStep.chase),
        (WaitStatus.waiting, 2, NOW, ChaseStep.escalate),
        (WaitStatus.received, 0, NOW, ChaseStep.none),
        (WaitStatus.escalated, 2, NOW, ChaseStep.none),
        (WaitStatus.cancelled, 0, NOW, ChaseStep.none),
    ],
)
def test_ladder(status: WaitStatus, chases: int, due: datetime, expected: ChaseStep) -> None:
    assert next_step(status, chases, due, POLICY, NOW) is expected
