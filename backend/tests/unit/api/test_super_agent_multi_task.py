"""Several requests in one Super Agent message: every plan step runs, the answers merge in plan order, and a step that
fails never hides the others (`ask_agent` with a stubbed planner, and `intent_responses.compose` directly)."""

from unittest.mock import MagicMock, patch
from uuid import UUID

import pytest
from fastapi.testclient import TestClient

from app.api.agent.intent_responses import Segment, compose
from app.contracts import ConciergePlan, Intent, PlanStep
from app.core.settings import Settings
from app.db.enums import MemoryStatus
from app.db.models import Company, MemoryItem
from app.main import create_app
from app.pipeline.concierge import StepResult
from app.pipeline.concierge_base import NOT_FOUND, STEP_FAILED
from tests.api_auth import as_owner, with_conversation

SETTINGS = Settings(database_url="postgresql+psycopg://u:p@localhost:1/db", env="test", _env_file=None)
URL = "/api/agent/ask"
RULE = "Rent is due on the 1st"
DONE = StepResult(Intent.task_done, True, "Done: Fix the roof", {"task_id": str(UUID(int=7))}, "tasks")
LISTED = StepResult(Intent.list_tasks, True, "Open tasks:\n1. [normal] Call the plumber #c0ffee", {}, "tasks")


def _step(intent: Intent, *, text: str | None = None, task_ref: str | None = None) -> PlanStep:
    return PlanStep(intent=intent, case_id=None, task_ref=task_ref, text=text, view=None)


def _plan(*steps: PlanStep, reply: str | None = None) -> ConciergePlan:
    return ConciergePlan(in_scope=True, steps=list(steps), reply=reply)


def _session() -> MagicMock:
    """A fake session with no stored rule (the real `record_owner_memory` adds one) and no portfolio rows."""
    sess = MagicMock()

    def scalars(query: object) -> MagicMock:
        result = MagicMock()
        is_company = "from companies" in str(query).lower()
        result.first.return_value = Company(id=UUID(int=1), name="EstateOS Test") if is_company else None
        result.all.return_value = []
        return result

    sess.scalars.side_effect = scalars
    sess.scalar.return_value = None
    sess.get.side_effect = with_conversation(lambda _model, _ident: None)
    sess.__enter__.return_value = sess
    return sess


def _ask(plan: ConciergePlan, query: str, run_plan: MagicMock) -> tuple[dict, MagicMock]:
    sess = _session()
    app = as_owner(create_app(SETTINGS, engine=MagicMock()))
    with (
        patch("app.api.agent.routes.Session", return_value=sess),
        patch("app.api.agent.routes.run_agent") as planner,
        patch("app.api.agent.routes.run_plan", run_plan),
        TestClient(app) as client,
    ):
        planner.return_value.output = plan
        res = client.post(URL, json={"query": query})
    assert res.status_code == 200
    planner.assert_called_once()
    return res.json(), sess


def _rules(sess: MagicMock) -> list[MemoryItem]:
    return [c.args[0] for c in sess.add.call_args_list if isinstance(c.args[0], MemoryItem)]


def test_three_requests_in_one_message_run_in_order() -> None:
    plan = _plan(
        _step(Intent.task_done, task_ref="a1b2c3"), _step(Intent.remember, text=RULE), _step(Intent.list_tasks)
    )
    run_plan = MagicMock(return_value=[DONE, LISTED])
    data, sess = _ask(
        plan, "mark #a1b2c3 done, remember that rent is due on the 1st, and what is on my list?", run_plan
    )

    run_plan.assert_called_once()  # the task steps ran together, the rule step never went to run_plan
    assert [s.intent for s in run_plan.call_args.args[3].steps] == [Intent.task_done, Intent.list_tasks]
    assert [(r.text, r.status) for r in _rules(sess)] == [(RULE, MemoryStatus.proposed)]
    answer = data["answer"]
    # the run_plan answer sits where its first step was asked (first), the rule after it
    assert answer.index("Done: Fix the roof") < answer.index("Open tasks:") < answer.index(f'"{RULE}"')
    assert "proposed standing rule" in answer
    assert [c["type"] for c in data["cards"]] == ["memory_item"]
    assert [c["type"] for c in data["previewCards"]] == ["memory_item"]
    assert any(a["actionType"] == "approve_memory" for a in data["actions"])


def test_a_failing_step_does_not_hide_the_others() -> None:
    plan = _plan(_step(Intent.task_done, task_ref="ffffff"), _step(Intent.remember, text=RULE))
    run_plan = MagicMock(return_value=[StepResult(Intent.task_done, False, NOT_FOUND, None, None)])
    data, sess = _ask(plan, "mark #ffffff done and remember that rent is due on the 1st", run_plan)

    assert NOT_FOUND in data["answer"]
    assert "proposed standing rule" in data["answer"]
    assert [r.text for r in _rules(sess)] == [RULE]
    assert [c["type"] for c in data["cards"]] == ["memory_item"]


def test_a_run_plan_error_does_not_hide_the_rule() -> None:
    plan = _plan(_step(Intent.list_tasks), _step(Intent.remember, text=RULE))
    data, sess = _ask(
        plan, "what is on my list, and remember that rent is due on the 1st", MagicMock(side_effect=OSError)
    )

    assert STEP_FAILED in data["answer"]
    assert "proposed standing rule" in data["answer"]
    assert [r.text for r in _rules(sess)] == [RULE]


def test_plan_with_only_run_plan_steps_is_unchanged() -> None:
    plan = _plan(_step(Intent.list_tasks))
    run_plan = MagicMock(return_value=[LISTED])
    data, sess = _ask(plan, "what is on my list?", run_plan)

    run_plan.assert_called_once()
    assert run_plan.call_args.args[3] is plan  # no sub-plan: the planner's own plan runs as before
    assert data["answer"] == LISTED.summary
    assert data["debugInfo"]["pipeline_stage"] == "llm_concierge"
    assert data["cards"] == []
    assert _rules(sess) == []


# ---- the composer itself ------------------------------------------------------------------------------------------


def _said(text: str) -> Segment:
    return Segment(text, [], [], [], None)


def test_compose_answers_api_steps_in_place_and_runs_the_rest_once() -> None:
    plan = _plan(
        _step(Intent.remember, text="one"),
        _step(Intent.list_tasks),
        _step(Intent.remember, text="two"),
        _step(Intent.task_done, task_ref="a1b2c3"),
    )
    runs: list[ConciergePlan] = []

    def run_rest(rest: ConciergePlan) -> list[StepResult]:
        runs.append(rest)
        return [LISTED, DONE]

    segments = compose(plan, {Intent.remember: lambda step: _said(f"rule {step.text}")}, run_rest)

    assert [s.text for s in segments] == ["rule one", f"{LISTED.summary}\n{DONE.summary}", "rule two"]
    assert [[s.intent for s in r.steps] for r in runs] == [[Intent.list_tasks, Intent.task_done]]


def test_compose_turns_an_error_into_that_segments_own_text() -> None:
    plan = _plan(_step(Intent.remember, text="bad"), _step(Intent.list_tasks), _step(Intent.remember, text="good"))

    def remember(step: PlanStep) -> Segment:
        if step.text == "bad":
            raise RuntimeError("db hiccup")
        return _said("rule good")

    def run_rest(_rest: ConciergePlan) -> list[StepResult]:
        raise OSError("connection reset")

    segments = compose(plan, {Intent.remember: remember}, run_rest)

    assert [s.text for s in segments] == [STEP_FAILED, STEP_FAILED, "rule good"]


def test_compose_without_api_steps_runs_the_plan_as_given() -> None:
    plan = _plan(_step(Intent.answer), reply="All quiet today.")
    runs: list[ConciergePlan] = []
    compose(plan, {Intent.remember: lambda _s: _said("rule")}, lambda rest: runs.append(rest) or [LISTED])
    assert len(runs) == 1
    assert runs[0] is plan


@pytest.mark.parametrize("needs_research", [False, True])
def test_a_reply_never_sits_beside_an_api_step(needs_research: bool) -> None:
    """The model's own reply (or research) is shown only for an all-read plan; dropping the `remember` step from the
    sub-plan must not make the rest look read-only (concierge_reply.reply_allowed)."""
    plan = ConciergePlan(
        in_scope=True,
        steps=[_step(Intent.remember, text="one"), _step(Intent.answer)],
        reply=None if needs_research else "Done, I saved it and sent it to everyone.",
        needs_research=needs_research,
    )
    runs: list[ConciergePlan] = []
    compose(plan, {Intent.remember: lambda _s: _said("rule")}, lambda rest: runs.append(rest) or [])
    [rest] = runs
    assert ([s.intent for s in rest.steps], rest.reply, rest.needs_research) == ([Intent.answer], None, False)
