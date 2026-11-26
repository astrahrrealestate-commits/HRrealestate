"""Per-turn timings: stage ms from an injected clock, merged into the stored JSONB, never lost on a retry."""

from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Any
from unittest.mock import MagicMock, patch
from uuid import UUID, uuid4

import pytest
from sqlalchemy import update
from sqlalchemy.dialects import postgresql

from app.contracts import ConciergePlan, Intent, PlanStep
from app.core.settings import Settings
from app.db.models import AgentTurn
from app.llm.calls import CallResult
from app.pipeline import concierge, owner_commands
from app.pipeline import concierge_turns as ct
from app.pipeline.concierge_base import StepResult
from app.pipeline.concierge_outcome import Outcome
from app.pipeline.turn_timings import KEYS, TurnTimer, merged, started, to_ms

AT = datetime(2026, 10, 22, 9, 0, tzinfo=UTC)
M = "app.pipeline.concierge_turns"
STEP = PlanStep(intent=Intent.list_tasks, case_id=None, task_ref=None, text=None, view=None)
PLAN = ConciergePlan(in_scope=True, steps=[STEP], reply=None)


class Clock:
    """Monotonic seconds that only move when a patched stage says so."""

    def __init__(self) -> None:
        self.now = 100.0

    def __call__(self) -> float:
        return self.now

    def spend(self, seconds: float, result: Any = None) -> Any:
        self.now += seconds
        return result


def _sql(stmt: Any) -> str:
    return str(stmt.compile(dialect=postgresql.dialect()))


def test_timer_measures_stages_adds_repeats_and_totals() -> None:
    clock = Clock()
    timer = TurnTimer(clock)
    with timer.measure("planner_ms"):
        clock.spend(0.8004)
    for _ in range(2):
        with timer.measure("answer_ms"):
            clock.spend(0.25)
    clock.spend(0.1)
    assert timer.snapshot() == {"planner_ms": 800, "answer_ms": 500}
    assert timer.final() == {"planner_ms": 800, "answer_ms": 500, "total_ms": 1400}


def test_a_stage_that_raises_is_still_measured() -> None:
    clock = Clock()
    timer = TurnTimer(clock)

    def failing_call() -> None:
        with timer.measure("planner_ms"):
            clock.spend(2.0)
            raise RuntimeError("model down")

    with pytest.raises(RuntimeError):
        failing_call()
    assert timer.stages == {"planner_ms": 2000}


def test_ms_are_whole_and_never_negative() -> None:
    assert (to_ms(0.0004), to_ms(0.0006), to_ms(-1.0)) == (0, 1, 0)


def test_keys_are_the_documented_set() -> None:
    assert KEYS == (
        "queue_wait_ms", "page_resolve_ms", "planner_ms", "executor_ms", "answer_ms", "total_ms", "attempts",
        "warm_hit", "first_delta_ms"
    )  # fmt: skip


def test_writes_merge_into_the_stored_object_instead_of_replacing_it() -> None:
    compiled = update(AgentTurn).values(timings=merged({"planner_ms": 812})).compile(dialect=postgresql.dialect())
    assert "timings=(coalesce(agent_turns.timings, '{}'::jsonb) || %(timings_new)s::JSONB)" in str(compiled)
    assert compiled.params["timings_new"] == {"planner_ms": 812}  # numbers only


def test_a_start_keeps_the_first_queue_wait_and_counts_attempts() -> None:
    sql = _sql(update(AgentTurn).values(timings=started()))
    wait = "CAST(floor(EXTRACT(epoch FROM clock_timestamp() - agent_turns.created_at)"
    assert wait in sql  # database clock on both sides: created (API insert) -> this run's start
    first, stored, attempts = (
        sql.index("jsonb_build_object("),
        sql.index("|| coalesce(agent_turns.timings, '{}'::jsonb))"),
        sql.rindex("|| jsonb_build_object("),
    )
    assert first < stored < attempts  # stored keys override the fresh queue wait; attempts overrides the stored count
    assert "coalesce(CAST((agent_turns.timings ->> %(timings_1)s::TEXT) AS INTEGER)" in sql


def test_turn_writes_carry_timings_with_the_db_clock_and_company_scope() -> None:
    session_cls = MagicMock()
    session = session_cls.return_value.__enter__.return_value
    session.scalar.return_value = MagicMock(status="pending")
    with patch(f"{M}.Session", session_cls):
        ct._start(MagicMock(), uuid4())
        ct._update(MagicMock(), uuid4(), uuid4(), {"plan": {}}, timings={"planner_ms": 3})
        ct._finish(MagicMock(), uuid4(), uuid4(), Outcome("ok"), timings={"total_ms": 9})
    start, upd, finish = (_sql(c.args[0]) for c in session.execute.call_args_list)
    assert "jsonb_build_object" in start
    for sql in (upd, finish):
        assert "timings=(coalesce(agent_turns.timings, '{}'::jsonb) ||" in sql
    for sql in (start, upd, finish):
        assert "updated_at=clock_timestamp()" in sql
        assert "agent_turns.company_id = " in sql


def _start(plan: dict[str, Any] | None = None) -> ct.TurnStart:
    return ct.TurnStart(uuid4(), uuid4(), uuid4(), "what is open?", AT, None, plan, {"view": "inbox"})


@pytest.fixture
def staged() -> Iterator[tuple[Clock, dict[str, MagicMock]]]:
    clock = Clock()
    result = CallResult(output=PLAN, model_call_id=uuid4())
    listed = [StepResult(Intent.list_tasks, True, "No open tasks.", None, "tasks")]
    with (
        patch(f"{M}._page", side_effect=lambda _e, s: clock.spend(0.2, s)),
        patch(f"{M}._brief", side_effect=lambda *_: clock.spend(0.05, ([], [], []))),
        patch(f"{M}.run_agent", side_effect=lambda *a, **k: clock.spend(0.8, result)),
        patch(f"{M}.run_plan", side_effect=lambda *a, **k: clock.spend(0.3, listed)),
        patch(f"{M}._brief_case_ids", return_value=[]),
        patch(f"{M}.load_history", return_value=[]),
        patch(f"{M}._update") as upd,
        patch(f"{M}._finish") as finish,
    ):
        yield clock, {"update": upd, "finish": finish}


def test_run_turn_records_each_stage_and_the_total(staged: tuple[Clock, dict[str, MagicMock]]) -> None:
    clock, io = staged
    start = _start()
    with patch(f"{M}._start", side_effect=lambda *_: clock.spend(0.01, start)):
        ct.run_turn(MagicMock(), MagicMock(), start.turn_id, clock=clock)
    timings = io["finish"].call_args.kwargs["timings"]
    assert timings == {"page_resolve_ms": 200, "planner_ms": 800, "executor_ms": 300, "total_ms": 1360}
    stored_with_plan = io["update"].call_args_list[0].kwargs["timings"]
    assert stored_with_plan == {"page_resolve_ms": 200, "planner_ms": 800}  # saved with the plan: a retry keeps it


def test_a_retry_with_a_stored_plan_sends_no_planner_time_so_the_first_one_stays(
    staged: tuple[Clock, dict[str, MagicMock]],
) -> None:
    clock, io = staged
    start = _start(plan=PLAN.model_dump(mode="json"))
    with patch(f"{M}._start", return_value=start):
        ct.run_turn(MagicMock(), MagicMock(), start.turn_id, clock=clock)
    timings = io["finish"].call_args.kwargs["timings"]
    assert timings == {"executor_ms": 300, "total_ms": 300}  # merged over the stored planner_ms, never replacing it


def test_a_transient_failure_still_left_its_stored_stage_times(staged: tuple[Clock, dict[str, MagicMock]]) -> None:
    clock, io = staged
    start = _start()
    with (
        patch(f"{M}._start", return_value=start),
        patch(f"{M}.run_plan", side_effect=OSError("db gone")),
        pytest.raises(OSError),
    ):
        ct.run_turn(MagicMock(), MagicMock(), start.turn_id, clock=clock)
    io["finish"].assert_not_called()
    assert io["update"].call_args_list[0].kwargs["timings"] == {"page_resolve_ms": 200, "planner_ms": 800}


def test_the_owner_qa_answer_call_is_timed_inside_the_executor() -> None:
    clock = Clock()
    timer = TurnTimer(clock)
    answer = PlanStep(intent=Intent.answer, case_id=None, task_ref=None, text=None, view=None)
    plan = ConciergePlan(in_scope=True, steps=[answer], reply=None)
    settings = Settings(database_url="postgresql+psycopg://u:p@localhost:1/db", _env_file=None)  # type: ignore[arg-type]
    with patch.object(owner_commands, "run_command", side_effect=lambda *a, **k: clock.spend(0.6, "Two cases.")):
        concierge.run_plan(MagicMock(), settings, UUID(int=1), plan, question="what?", now=AT, timer=timer)
    assert timer.stages == {"answer_ms": 600}


def test_a_direct_reply_makes_no_answer_call_to_time() -> None:
    timer = TurnTimer(Clock())
    answer = PlanStep(intent=Intent.answer, case_id=None, task_ref=None, text=None, view=None)
    plan = ConciergePlan(in_scope=True, steps=[answer], reply="Two cases are open.")
    settings = Settings(database_url="postgresql+psycopg://u:p@localhost:1/db", _env_file=None)  # type: ignore[arg-type]
    concierge.run_plan(MagicMock(), settings, UUID(int=1), plan, question="what?", now=AT, timer=timer)
    assert timer.stages == {}


def test_turn_timings_includes_warm_hit_and_first_delta() -> None:
    from app.pipeline.turn_timings import FIRST_DELTA, WARM_HIT

    assert WARM_HIT in KEYS
    assert FIRST_DELTA in KEYS
    stmt = update(AgentTurn).values(timings=merged({"warm_hit": "facts", "first_delta_ms": 350}))
    sql = _sql(stmt)
    assert "||" in sql
