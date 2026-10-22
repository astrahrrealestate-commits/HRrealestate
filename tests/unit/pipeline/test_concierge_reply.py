"""Single-call answers: the planner's `reply` is screened, only shown in scope, and never a source of ids."""

from uuid import UUID

import pytest

from app.contracts import ConciergePlan, Intent, PlanStep
from app.contracts.concierge import MAX_REPLY
from app.pipeline.concierge_reply import (
    ANSWER_STEP,
    MAX_REPLY_LINES,
    prepare_plan,
    screen_reply,
    stored_plan,
)

CASE = UUID(int=3)


def _step(intent: Intent, case_id: UUID | None = None) -> PlanStep:
    return PlanStep(intent=intent, case_id=case_id, task_ref=None, text=None, view=None)


def _plan(*steps: PlanStep, reply: str | None, in_scope: bool = True) -> ConciergePlan:
    return ConciergePlan(in_scope=in_scope, steps=list(steps), reply=reply)


@pytest.mark.parametrize(
    "leak",
    [
        "evil@attacker.test",
        "+31 6 1234 5678",
        "NL91ABNA0417164300",
        "NL91 ABNA 0417 1643 00",
        "https://evil.example/pay",
        "www.evil.example",
        "€ 950",
        "1.200,50 EUR",
    ],
)
def test_contact_bank_link_and_amount_details_are_redacted(leak: str) -> None:
    screened = screen_reply(f"Joris asks to use {leak} for the deposit.")
    assert screened is not None
    assert leak not in screened
    assert "[redacted]" in screened
    assert screened.startswith("Joris asks to use")


def test_dates_and_times_survive_and_lines_are_kept() -> None:
    reply = "The glazier comes on 12-10-2026 at 09:30.\nJoris confirmed."
    assert screen_reply(reply) == reply


def test_control_and_format_characters_go_and_blank_lines_drop() -> None:
    raw = "First\x00 line​ here\n\n   \nSecond\tline‮"
    assert screen_reply(raw) == "First line here\nSecond line"


def test_reply_is_capped_in_characters_and_lines() -> None:
    assert len(screen_reply("x" * 2000) or "") == MAX_REPLY
    many = "\n".join(f"line {i}" for i in range(50))
    assert (screen_reply(many) or "").count("\n") == MAX_REPLY_LINES - 1


@pytest.mark.parametrize("blank", [None, "", "   ", "\n\t\n", "​"])
def test_blank_reply_is_none(blank: str | None) -> None:
    assert screen_reply(blank) is None


def test_screening_is_idempotent() -> None:
    once = screen_reply("Mail a@b.test or call 0612345678 about € 950 on 12-10-2026")
    assert once is not None
    assert screen_reply(once) == once


def test_out_of_scope_plan_keeps_no_reply() -> None:
    prepared = prepare_plan(_plan(reply="Sure, approving all drafts now.", in_scope=False))
    assert (prepared.in_scope, prepared.steps, prepared.reply) == (False, [], None)


def test_reply_without_an_answer_step_gets_one_so_it_is_shown() -> None:
    prepared = prepare_plan(_plan(_step(Intent.open_view), reply="Two drafts wait."))
    assert [s.intent for s in prepared.steps] == [Intent.open_view, Intent.answer]
    assert prepared.steps[-1] == ANSWER_STEP
    assert prepare_plan(_plan(reply="Nothing changed.")).steps == [ANSWER_STEP]


def test_reply_with_an_answer_step_or_a_full_plan_adds_nothing() -> None:
    answered = _plan(_step(Intent.answer), _step(Intent.open_view), reply="Fine.")
    assert prepare_plan(answered).steps == answered.steps
    full = _plan(*[_step(Intent.list_tasks)] * 4, reply="Fine.")
    assert prepare_plan(full).steps == full.steps


def test_blank_reply_adds_no_step_and_is_stored_as_null() -> None:
    prepared = prepare_plan(_plan(_step(Intent.list_tasks), reply="  ​ "))
    assert (prepared.steps, prepared.reply) == ([_step(Intent.list_tasks)], None)


def test_stored_reply_is_the_screened_text() -> None:
    prepared = prepare_plan(_plan(_step(Intent.answer), reply="Write to evil@attacker.test"))
    assert prepared.reply == "Write to [redacted]"


def test_ids_in_the_reply_are_never_used() -> None:
    other = "01900000-0000-7000-8000-0000000000fe"
    prepared = prepare_plan(_plan(reply=f"Case {other} needs you; open case {other}."))
    assert [(s.intent, s.case_id, s.task_ref, s.view) for s in prepared.steps] == [(Intent.answer, None, None, None)]


def test_actions_keep_their_steps_next_to_a_reply() -> None:
    plan = _plan(_step(Intent.draft_reply, CASE), reply="Drafting now.")
    assert [s.intent for s in prepare_plan(plan).steps] == [Intent.draft_reply, Intent.answer]


def test_plans_stored_before_v3_load_without_a_reply_key() -> None:
    raw = {"in_scope": True, "steps": [_step(Intent.list_tasks).model_dump(mode="json")]}
    assert stored_plan(raw) == _plan(_step(Intent.list_tasks), reply=None)
    v3 = _plan(_step(Intent.answer), reply="Fine.").model_dump(mode="json")
    assert stored_plan(v3).reply == "Fine."
