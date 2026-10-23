"""Per-turn timings (spec amendment 2026-10-22): stage milliseconds stored in `agent_turns.timings` (JSONB).

Keys (all integers): `queue_wait_ms` (turn created -> this run started, both on the database clock),
`page_resolve_ms`, `planner_ms`, `executor_ms` (includes `answer_ms` when the answer step asked owner_qa),
`answer_ms` (owner_qa calls: the answer step without a usable `reply`, or the planner-failure fallback), `total_ms`
(this attempt, from just before it locked the turn to just before its final write) and `attempts` (runs started).
Stage times use an injected monotonic clock (`time.monotonic` in production) so tests are exact.

Every write MERGES into the stored object (`timings || new`), so a retry never loses what an earlier attempt stored:
`queue_wait_ms` keeps the first start's value, `attempts` counts every start, and a stage keeps the latest attempt
that measured it (a retry that reuses a stored plan keeps the first attempt's `planner_ms`). The values are numbers
only, never text, and are not logged beyond numbers.
"""

import time
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from typing import Any

from sqlalchemy import ColumnElement, Integer, bindparam, cast, extract, func, literal_column
from sqlalchemy.dialects.postgresql import JSONB

from app.db.models import AgentTurn

QUEUE_WAIT = "queue_wait_ms"
PAGE_RESOLVE = "page_resolve_ms"
PLANNER = "planner_ms"
EXECUTOR = "executor_ms"
ANSWER = "answer_ms"
TOTAL = "total_ms"
ATTEMPTS = "attempts"
KEYS = (QUEUE_WAIT, PAGE_RESOLVE, PLANNER, EXECUTOR, ANSWER, TOTAL, ATTEMPTS)

Clock = Callable[[], float]  # seconds, monotonic


def to_ms(seconds: float) -> int:
    return max(0, round(seconds * 1000))


class TurnTimer:
    """Stage durations of one attempt. `measure` adds up when a stage runs more than once."""

    def __init__(self, clock: Clock = time.monotonic) -> None:
        self._clock = clock
        self._started = clock()
        self.stages: dict[str, int] = {}

    @contextmanager
    def measure(self, stage: str) -> Iterator[None]:
        began = self._clock()
        try:
            yield
        finally:
            self.stages[stage] = self.stages.get(stage, 0) + to_ms(self._clock() - began)

    def snapshot(self) -> dict[str, int]:
        return dict(self.stages)

    def final(self) -> dict[str, int]:
        return {**self.stages, TOTAL: to_ms(self._clock() - self._started)}


def _stored() -> ColumnElement[Any]:
    return func.coalesce(AgentTurn.timings, literal_column("'{}'::jsonb", JSONB))


def merged(new: Mapping[str, int]) -> ColumnElement[Any]:
    """`coalesce(timings, '{}') || new`: new keys win, every other stored key stays."""
    return _stored().op("||", return_type=JSONB)(bindparam("timings_new", dict(new), type_=JSONB))


def started() -> ColumnElement[Any]:
    """At a run's start: `queue_wait_ms` from the database clock unless an earlier start stored it, `attempts` + 1."""
    waited = cast(func.floor(extract("epoch", func.clock_timestamp() - AgentTurn.created_at) * 1000), Integer)
    attempts = func.coalesce(AgentTurn.timings[ATTEMPTS].as_integer(), 0) + 1
    first = func.jsonb_build_object(QUEUE_WAIT, waited, type_=JSONB)
    return first.op("||", return_type=JSONB)(_stored()).op("||", return_type=JSONB)(
        func.jsonb_build_object(ATTEMPTS, attempts, type_=JSONB)
    )
