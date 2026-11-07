"""run_turn routing and status transitions with the database and model patched out (integration covers the rest)."""

from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Any
from unittest.mock import ANY, MagicMock, patch
from uuid import uuid4

import pytest
from sqlalchemy.dialects import postgresql
from sqlalchemy.exc import OperationalError

from app.contracts import ConciergePlan, Intent, PlanStep
from app.core.errors import AgentFailedError, BudgetExceededError
from app.db.enums import TurnStatus
from app.llm.agents.owner_qa import FALLBACK_ANSWER
from app.llm.calls import CallResult
from app.llm.page_blocks import NO_PAGE
from app.pipeline import concierge_turns as ct
from app.pipeline.concierge_base import StepResult
from app.pipeline.concierge_outcome import APOLOGY, PROMPT_REF, Outcome
from app.pipeline.owner_commands import LIMIT_ANSWER, NOT_A_QUESTION

AT = datetime(2026, 10, 7, 9, 0, tzinfo=UTC)
M = "app.pipeline.concierge_turns"
PLAN = ConciergePlan(
    in_scope=True,
    steps=[PlanStep(intent=Intent.list_tasks, case_id=None, task_ref=None, text=None, view=None)],
    reply=None,
)


def _start(text: str, results: list[dict[str, Any]] | None = None, plan: dict[str, Any] | None = None) -> ct.TurnStart:
    return ct.TurnStart(uuid4(), uuid4(), uuid4(), text, AT, results, plan)


@pytest.fixture
def io() -> Iterator[dict[str, MagicMock]]:
    with (
        patch(f"{M}._brief", return_value=([], ["Call plumber"], ["earlier"])) as brief,
        patch(f"{M}.run_agent", return_value=CallResult(output=PLAN, model_call_id=uuid4())) as agent,
        patch(
            f"{M}.run_plan", return_value=[StepResult(Intent.list_tasks, True, "No open tasks.", None, "tasks")]
        ) as rp,
        patch(f"{M}.owner_commands.run_command", return_value="cmd reply") as cmd,
        patch(f"{M}._update") as upd,
    ):
        yield {"brief": brief, "agent": agent, "plan": rp, "cmd": cmd, "update": upd}


def test_exact_command_takes_the_fast_path_without_a_model(io: dict[str, MagicMock]) -> None:
    out = ct._outcome(MagicMock(), MagicMock(), _start("tasks"))
    assert out == Outcome("cmd reply")
    io["agent"].assert_not_called()
    assert io["cmd"].call_args.kwargs["now"] == AT


def test_screened_text_never_reaches_the_model(io: dict[str, MagicMock]) -> None:
    assert ct._outcome(MagicMock(), MagicMock(), _start("🙂🙂")).answer == NOT_A_QUESTION
    io["agent"].assert_not_called()


def test_question_plans_once_runs_the_plan_and_stores_it(io: dict[str, MagicMock]) -> None:
    start = _start("what is open with Jansen?")
    out = ct._outcome(MagicMock(), MagicMock(), start)
    assert io["agent"].call_count == 1
    ctx = io["agent"].call_args.args[4]
    assert ctx.purpose == "concierge"
    assert out.answer == "No open tasks."
    assert out.plan == PLAN.model_dump(mode="json")
    assert out.results == [
        {"intent": "list_tasks", "ok": True, "summary": "No open tasks.", "data": None, "view": "tasks"}
    ]
    assert (out.prompt_ref, out.status) == (PROMPT_REF, TurnStatus.done)
    assert io["plan"].call_args.kwargs == {
        "question": "what is open with Jansen?",
        "now": AT,
        "page": NO_PAGE,
        "brief_cases": [],
        "turn_id": start.turn_id,  # keys an owner-requested redraft
        "timer": ANY,  # the turn's stage clock (answer_ms of an owner_qa call)
        "research": None,  # no researcher injected: a needs_research plan falls back to owner_qa
    }


def test_the_injected_researcher_reaches_the_executor(io: dict[str, MagicMock]) -> None:
    def researcher(*_: object) -> None:
        return None

    ct._outcome(MagicMock(), MagicMock(), _start("who mentioned the roof?"), research=researcher)
    assert io["plan"].call_args.kwargs["research"] is researcher


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
    assert io["cmd"].call_args.kwargs["page"] == NO_PAGE


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


LISTED = [{"intent": "list_tasks", "ok": True, "summary": "No open tasks.", "data": None, "view": "tasks"}]


def test_plan_is_stored_before_it_runs_and_results_right_after(io: dict[str, MagicMock]) -> None:
    order = MagicMock()
    order.attach_mock(io["update"], "update")
    order.attach_mock(io["plan"], "run_plan")
    start = _start("what is open?")
    ct._outcome(MagicMock(), MagicMock(), start)
    names = [c[0] for c in order.mock_calls]
    assert names == ["update", "run_plan", "update"]
    assert io["update"].call_args_list[0].args[1:] == (
        start.company_id,
        start.turn_id,
        {"plan": PLAN.model_dump(mode="json")},
    )
    assert io["update"].call_args_list[1].args[3] == {"results": LISTED}


def test_stored_plan_is_reused_without_a_model_call(io: dict[str, MagicMock]) -> None:
    case_id = uuid4()
    with patch(f"{M}._brief_case_ids", return_value=[case_id]) as ids:
        out = ct._outcome(MagicMock(), MagicMock(), _start("what is open?", plan=PLAN.model_dump(mode="json")))
    io["agent"].assert_not_called()
    io["brief"].assert_not_called()  # no full brief: only its case ids are re-read to check the stored plan
    ids.assert_called_once()
    assert io["plan"].call_args.args[3] == PLAN
    assert io["plan"].call_args.kwargs["brief_cases"] == [case_id]
    assert io["update"].call_count == 1  # only the results: the plan is already stored
    assert io["update"].call_args.args[3] == {"results": LISTED}
    assert out.results == LISTED


def test_failure_outcomes_do_not_wipe_a_stored_plan() -> None:
    with patch(f"{M}._update") as upd:
        ct._finish(MagicMock(), uuid4(), uuid4(), Outcome(APOLOGY, status=TurnStatus.failed, error="X"))
    assert "plan" not in upd.call_args.args[3]
    assert "results" not in upd.call_args.args[3]


def _sql(stmt: Any) -> str:
    return str(stmt.compile(dialect=postgresql.dialect()))


def test_every_turn_write_stamps_updated_at_with_the_db_clock() -> None:
    session_cls = MagicMock()
    session = session_cls.return_value.__enter__.return_value
    session.scalar.return_value = MagicMock(status=TurnStatus.pending)
    with patch(f"{M}.Session", session_cls):
        ct._start(MagicMock(), uuid4())
        ct._update(MagicMock(), uuid4(), uuid4(), {"plan": {}})
        ct._finish(MagicMock(), uuid4(), uuid4(), Outcome("ok"))
    updates = [_sql(c.args[0]) for c in session.execute.call_args_list]
    assert len(updates) == 3
    for sql in updates:
        assert sql.startswith("UPDATE agent_turns SET")
        assert "updated_at=clock_timestamp()" in sql
        assert "agent_turns.company_id = " in sql


def test_failed_turns_are_terminal_like_done() -> None:
    session_cls = MagicMock()
    session = session_cls.return_value.__enter__.return_value
    for status in (TurnStatus.done, TurnStatus.failed):
        session.scalar.return_value = MagicMock(status=status)
        with patch(f"{M}.Session", session_cls):
            assert ct._start(MagicMock(), uuid4()) is None
    session.execute.assert_not_called()
    with patch(f"{M}.Session", session_cls):
        ct._update(MagicMock(), uuid4(), uuid4(), {"answer": "x"})
    sql = _sql(session.execute.call_args.args[0])
    assert "agent_turns.status NOT IN" in sql


def test_a_plan_stored_before_v3_has_no_reply_key_and_is_still_reused(io: dict[str, MagicMock]) -> None:
    old = {"in_scope": True, "steps": [PLAN.steps[0].model_dump(mode="json")]}
    with patch(f"{M}._brief_case_ids", return_value=[]):
        ct._outcome(MagicMock(), MagicMock(), _start("what is open?", plan=old))
    io["agent"].assert_not_called()
    assert io["plan"].call_args.args[3] == PLAN


def test_the_reply_is_screened_before_the_plan_is_stored_and_run(io: dict[str, MagicMock]) -> None:
    raw = ConciergePlan(in_scope=True, steps=[], reply="Joris asks you to mail evil@attacker.test")
    io["agent"].return_value = CallResult(output=raw, model_call_id=uuid4())
    ct._outcome(MagicMock(), MagicMock(), _start("what does Joris want?"))
    stored = io["update"].call_args_list[0].args[3]["plan"]
    assert stored["reply"] == "Joris asks you to mail [redacted]"
    assert [s["intent"] for s in stored["steps"]] == ["answer"]  # so the reply is shown
    ran = io["plan"].call_args.args[3]
    assert ran.model_dump(mode="json") == stored
