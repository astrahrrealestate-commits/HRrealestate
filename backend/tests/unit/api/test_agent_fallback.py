"""The Super Agent's answer when the model could not answer: honest, on topic, and never made-up data."""

import pytest

from app.api.agent.fallback import domain_fallback_answer

LIVE = "• Keizersgracht 42-A: boiler error (high)"


@pytest.mark.parametrize(
    "query",
    [
        "What open cases do I have?",
        "show active tickets",
        "Any pending requests?",
        "what's open",
        "list outstanding issues",
    ],
)
def test_a_question_about_open_work_gets_the_live_case_list(query: str) -> None:
    answer = domain_fallback_answer(query, live_cases_text=LIVE, is_error=True)
    assert LIVE in answer


def test_open_work_with_nothing_open_says_zero() -> None:
    assert "0 open" in domain_fallback_answer("open cases?", live_cases_text="", is_error=True)


@pytest.mark.parametrize(
    "query",
    [
        "List active leases",
        "Who is the active tenant at Keizersgracht?",
        "status of the unit",
        "which contractor fixes leaks",
    ],
)
def test_other_questions_are_not_answered_with_the_case_list_or_invented_facts(query: str) -> None:
    answer = domain_fallback_answer(query, live_cases_text=LIVE, is_error=True)
    assert LIVE not in answer
    for invented in ("Vipin", "Kevin", "Standing Contractor Rule", "Registered Contractors"):
        assert invented not in answer
    assert "can't answer" in answer


def test_a_non_error_miss_is_honest_too() -> None:
    answer = domain_fallback_answer("something odd", live_cases_text=LIVE, is_error=False)
    assert LIVE not in answer
    assert "No automated actions were performed" in answer
