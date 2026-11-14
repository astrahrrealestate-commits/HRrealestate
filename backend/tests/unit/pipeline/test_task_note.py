"""The note after "Task added": what a to-do is not, what became of an amount, and how to remove it."""

import pytest

from app.pipeline.task_note import task_note


@pytest.mark.parametrize(
    "title",
    [
        "Dispatch Kevin van Dijk to Keizersgracht 42-A for the boiler",
        "Send payment nudges to tenants",
        "Pay the Visser invoice",
        "Book the electrician for Friday",
        "Remind Lotte about the lease",
    ],
)
def test_an_outbound_sounding_task_says_nothing_was_sent(title: str) -> None:
    note = task_note(title, "d1ff5b")
    assert "only a to-do" in note
    assert "Nothing was sent, booked or paid" in note


def test_an_ordinary_task_gets_only_the_removal_hint() -> None:
    note = task_note("Check the roof next week", "a1b2c3")
    assert "only a to-do" not in note
    assert 'Say "done #a1b2c3" to remove it.' in note


def test_a_redacted_amount_says_no_budget_was_recorded_or_checked() -> None:
    note = task_note("Dispatch Kevin with a budget of [redacted]", "d1ff5b")
    assert "amount was not kept" in note
    assert "no budget was recorded or checked against a cap" in note


def test_no_amount_no_amount_sentence() -> None:
    assert "amount" not in task_note("Dispatch Kevin to Singel 412", "d1ff5b")
