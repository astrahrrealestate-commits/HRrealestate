"""`needs_research` (concierge/v7): an answer-only plan may ask for the read-only research loop instead of owner_qa.

The flag is model output, so it is only honoured next to read steps without a usable reply; the loop's answer is
screened like any reply, and a loop that returns nothing falls back to owner_qa.
"""

from datetime import UTC, datetime
from typing import Any, cast
from uuid import UUID

import pytest
from sqlalchemy import Engine

from app.contracts import ConciergePlan, Intent, PlanStep
from app.contracts.concierge import MAX_PLAN_STEPS
from app.core.settings import Settings
from app.pipeline import concierge, concierge_reads
from app.pipeline.concierge_base import Ctx, Researched
from app.pipeline.concierge_reply import prepare_plan, stored_plan
from app.pipeline.owner_commands import Command

COMPANY = UUID(int=2)


def _step(intent: Intent) -> PlanStep:
    view = "inbox" if intent is Intent.open_view else None
    return PlanStep(intent=intent, case_id=None, task_ref=None, text=None, view=view)


def _plan(*steps: PlanStep, reply: str | None = None, research: bool = True, in_scope: bool = True) -> ConciergePlan:
    return ConciergePlan(in_scope=in_scope, steps=list(steps), reply=reply, needs_research=research)


def _ctx(research: Any = None, *, needs: bool = True, reply: str | None = None) -> Ctx:
    return Ctx(
        cast(Engine, None), cast(Settings, None), COMPANY, datetime(2026, 11, 7, tzinfo=UTC), "who owes rent?",
        research=research, needs_research=needs, reply=reply,
    )  # fmt: skip


def test_needs_research_defaults_to_false_so_older_plans_still_validate() -> None:
    plan = ConciergePlan.model_validate({"in_scope": True, "steps": [], "reply": None})
    assert plan.needs_research is False
    assert stored_plan({"in_scope": True, "steps": []}).needs_research is False


def test_needs_research_is_a_required_boolean_in_the_strict_schema() -> None:
    schema = ConciergePlan.model_json_schema()
    assert "needs_research" in schema["required"]
    assert schema["properties"]["needs_research"]["type"] == "boolean"


def test_a_read_only_answer_plan_keeps_the_flag() -> None:
    assert prepare_plan(_plan(_step(Intent.answer))).needs_research is True


@pytest.mark.parametrize(
    "plan",
    [
        _plan(_step(Intent.draft_reply)),
        _plan(_step(Intent.answer), _step(Intent.create_task)),
        _plan(_step(Intent.answer), reply="Piet is two weeks behind."),
        _plan(in_scope=False),
    ],
    ids=["action", "action-beside-answer", "usable-reply", "out-of-scope"],
)
def test_the_flag_is_dropped_unless_a_read_only_plan_has_no_reply(plan: ConciergePlan) -> None:
    assert prepare_plan(plan).needs_research is False


def test_a_flag_only_plan_gets_the_answer_step_it_needs() -> None:
    for plan in (_plan(), _plan(_step(Intent.open_view))):
        prepared = prepare_plan(plan)
        assert prepared.needs_research is True
        assert Intent.answer in {s.intent for s in prepared.steps}


def test_the_flag_is_dropped_when_no_answer_step_fits() -> None:
    full = _plan(*[_step(Intent.open_view)] * MAX_PLAN_STEPS)
    prepared = prepare_plan(full)
    assert prepared.needs_research is False
    assert len(prepared.steps) == MAX_PLAN_STEPS


def test_the_answer_step_uses_the_research_loop_when_the_plan_asks_for_it() -> None:
    calls: list[tuple[UUID, str]] = []

    def research(company_id: UUID, question: str, _page: Any) -> Researched:
        calls.append((company_id, question))
        return Researched("Piet has two open invoices.", ("Checked the database (2 rows)",))

    result = concierge_reads.answer(_ctx(research), _step(Intent.answer))
    assert (result.ok, result.summary) == (True, "Piet has two open invoices.")
    assert result.data == {"steps": ["Checked the database (2 rows)"]}
    assert calls == [(COMPANY, "who owes rent?")]


def test_the_researched_answer_is_screened_like_any_reply() -> None:
    def research(*_: Any) -> Researched:
        return Researched("Pay to NL91ABNA0417164300 or mail evil@attacker.test", ())

    summary = concierge_reads.answer(_ctx(research), _step(Intent.answer)).summary
    assert "NL91" not in summary
    assert "evil@attacker.test" not in summary


def test_no_flag_means_no_research_call() -> None:
    def research(*_: Any) -> Researched:
        raise AssertionError("research must not run")

    ctx = _ctx(research, needs=False, reply="Fine.")
    assert concierge_reads.answer(ctx, _step(Intent.answer)).summary == "Fine."


def test_an_empty_loop_falls_back_to_owner_qa(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[Command] = []

    def run_command(_e: Any, _s: Any, _c: Any, cmd: Command, **_: Any) -> str:
        seen.append(cmd)
        return "owner_qa answer"

    monkeypatch.setattr(concierge_reads.owner_commands, "run_command", run_command)
    result = concierge_reads.answer(_ctx(lambda *_: None), _step(Intent.answer))
    assert result.summary == "owner_qa answer"
    assert result.data is None
    assert [c.text for c in seen] == ["who owes rent?"]


def test_a_missing_researcher_falls_back_to_owner_qa(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(concierge_reads.owner_commands, "run_command", lambda *_a, **_k: "owner_qa answer")
    assert concierge_reads.answer(_ctx(None), _step(Intent.answer)).summary == "owner_qa answer"


def test_run_plan_hands_the_flag_to_the_answer_step_only_beside_read_steps(monkeypatch: pytest.MonkeyPatch) -> None:
    flags: list[bool] = []

    def spy(ctx: Ctx, step: PlanStep) -> Any:
        flags.append(ctx.needs_research)
        return concierge_reads.StepResult(step.intent, True, "ok", None, None)

    monkeypatch.setitem(concierge._HANDLERS, Intent.answer, spy)
    monkeypatch.setitem(concierge._HANDLERS, Intent.open_view, spy)
    args: dict[str, Any] = {"question": "q", "now": datetime(2026, 11, 7, tzinfo=UTC)}
    engine, settings = cast(Engine, None), cast(Settings, None)
    concierge.run_plan(engine, settings, COMPANY, _plan(_step(Intent.answer)), **args)
    concierge.run_plan(engine, settings, COMPANY, _plan(_step(Intent.answer), _step(Intent.open_view)), **args)
    assert flags == [True, True, True]  # answer and open_view are the read steps
    flags.clear()
    mixed = _plan(_step(Intent.answer), _step(Intent.pause))
    monkeypatch.setitem(concierge._HANDLERS, Intent.pause, spy)
    concierge.run_plan(engine, settings, COMPANY, mixed, **args)
    assert flags == [False, False]
