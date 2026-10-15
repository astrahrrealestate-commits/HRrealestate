"""run_turn routing and status transitions with the database and model patched out (integration covers the rest)."""

from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Any
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest
from sqlalchemy.exc import OperationalError

from app.contracts import ConciergePlan, Intent, PlanStep
from app.core.errors import AgentFailedError, BudgetExceededError
from app.db.enums import TurnStatus
from app.llm.agents.owner_qa import FALLBACK_ANSWER
from app.llm.calls import CallResult
from app.pipeline import concierge_turns as ct
from app.pipeline.concierge_base import StepResult
from app.pipeline.concierge_outcome import APOLOGY, PROMPT_REF, Outcome
from app.pipeline.owner_commands import LIMIT_ANSWER, NOT_A_QUESTION

AT = datetime(2026, 10, 7, 9, 0, tzinfo=UTC)
M = "app.pipeline.concierge_turns"
PLAN = ConciergePlan(
    in_scope=True, steps=[PlanStep(intent=Intent.list_tasks, case_id=None, task_ref=None, text=None, view=None)]
)


def _start(text: str, results: list[dict[str, Any]] | None = None) -> ct.TurnStart:
    return ct.TurnStart(uuid4(), uuid4(), uuid4(), text, AT, results, None)


@pytest.fixture
def io() -> Iterator[dict[str, MagicMock]]:
    with (
        patch(f"{M}._brief", return_value=([], ["Call plumber"], ["earlier"])) as brief,
        patch(f"{M}.run_agent", return_value=CallResult(output=PLAN, model_call_id=uuid4())) as agent,
        patch(
            f"{M}.run_plan", return_value=[StepResult(Intent.list_tasks, True, "No open tasks.", None, "tasks")]
        ) as rp,
        patch(f"{M}.owner_commands.run_command", return_value="cmd reply") as cmd,
    ):
        yield {"brief": brief, "agent": agent, "plan": rp, "cmd": cmd}


def test_exact_command_takes_the_fast_path_without_a_model(io: dict[str, MagicMock]) -> None:
    out = ct._outcome(MagicMock(), MagicMock(), _start("tasks"))
    assert out == Outcome("cmd reply")
    io["agent"].assert_not_called()
    assert io["cmd"].call_args.kwargs["now"] == AT


def test_screened_text_never_reaches_the_model(io: dict[str, MagicMock]) -> None:
    assert ct._outcome(MagicMock(), MagicMock(), _start("🙂🙂")).answer == NOT_A_QUESTION
    io["agent"].assert_not_called()


def test_question_plans_once_runs_the_plan_and_stores_it(io: dict[str, MagicMock]) -> None:
    out = ct._outcome(MagicMock(), MagicMock(), _start("what is open with Jansen?"))
    assert io["agent"].call_count == 1
    ctx = io["agent"].call_args.args[4]
    assert ctx.purpose == "concierge"
    assert out.answer == "No open tasks."
    assert out.plan == PLAN.model_dump(mode="json")
    assert out.results == [
        {"intent": "list_tasks", "ok": True, "summary": "No open tasks.", "data": None, "view": "tasks"}
    ]
    assert (out.prompt_ref, out.status) == (PROMPT_REF, TurnStatus.done)
    assert io["plan"].call_args.kwargs == {"question": "what is open with Jansen?", "now": AT}


def test_budget_spent_answers_the_limit_text(io: dict[str, MagicMock]) -> None:
    io["agent"].side_effect = BudgetExceededError("concierge_daily_calls")
    out = ct._outcome(MagicMock(), MagicMock(), _start("what now?"))
    assert out == Outcome(LIMIT_ANSWER)
    io["plan"].assert_not_called()


def test_planner_failure_falls_back_to_owner_qa(io: dict[str, MagicMock]) -> None:
    io["agent"].side_effect = AgentFailedError("concierge: boom")
    out = ct._outcome(MagicMock(), MagicMock(), _start("what now?"))
    assert out == Outcome("cmd reply")
    cmd = io["cmd"].call_args.args[3]
    assert (cmd.kind.value, cmd.text) == ("question", "what now?")


def test_owner_qa_failure_falls_back_to_fixed_text(io: dict[str, MagicMock]) -> None:
    io["agent"].side_effect = AgentFailedError("concierge: boom")
    io["cmd"].side_effect = KeyError("x")
    assert ct._outcome(MagicMock(), MagicMock(), _start("what now?")) == Outcome(FALLBACK_ANSWER)


def test_transient_planner_error_propagates(io: dict[str, MagicMock]) -> None:
    io["agent"].side_effect = OperationalError("select", {}, Exception("down"))
    with pytest.raises(OperationalError):
        ct._outcome(MagicMock(), MagicMock(), _start("what now?"))


def test_stored_results_finish_without_executing(io: dict[str, MagicMock]) -> None:
    stored = [{"intent": "list_tasks", "ok": True, "summary": "No open tasks.", "data": None, "view": "tasks"}]
    out = ct._outcome(MagicMock(), MagicMock(), _start("what now?", stored))
    assert out.answer == "No open tasks."
    assert out.results == stored
    io["agent"].assert_not_called()
    io["plan"].assert_not_called()
    io["cmd"].assert_not_called()


def test_run_turn_skips_a_done_or_missing_turn() -> None:
    with patch(f"{M}._start", return_value=None), patch(f"{M}._finish") as finish, patch(f"{M}._outcome") as oc:
        ct.run_turn(MagicMock(), MagicMock(), uuid4())
    oc.assert_not_called()
    finish.assert_not_called()


def test_run_turn_finishes_done() -> None:
    start = _start("tasks")
    with (
        patch(f"{M}._start", return_value=start),
        patch(f"{M}._outcome", return_value=Outcome("ok")),
        patch(f"{M}._finish") as finish,
    ):
        ct.run_turn(MagicMock(), MagicMock(), start.turn_id)
    assert finish.call_args.args[1:] == (start.company_id, start.turn_id, Outcome("ok"))


def test_run_turn_reraises_transient_without_finishing() -> None:
    with (
        patch(f"{M}._start", return_value=_start("q?")),
        patch(f"{M}._outcome", side_effect=OperationalError("x", {}, Exception("down"))),
        patch(f"{M}._finish") as finish,
        pytest.raises(OperationalError),
    ):
        ct.run_turn(MagicMock(), MagicMock(), uuid4())
    finish.assert_not_called()


def test_run_turn_other_error_fails_with_type_name_only() -> None:
    with (
        patch(f"{M}._start", return_value=_start("q?")),
        patch(f"{M}._outcome", side_effect=ValueError("Jansen 0612345678")),
        patch(f"{M}._finish") as finish,
    ):
        ct.run_turn(MagicMock(), MagicMock(), uuid4())
    outcome = finish.call_args.args[3]
    assert (outcome.status, outcome.answer, outcome.error) == (TurnStatus.failed, APOLOGY, "ValueError")
