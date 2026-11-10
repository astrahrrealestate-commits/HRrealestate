"""Questions about who owes or paid rent get an honest "no rent data yet" while none is mirrored."""

import pytest

from app.api.agent import rent_guard
from app.api.agent.rent_guard import NO_RENT_DATA_ANSWER, rent_data_answer


@pytest.mark.parametrize(
    "query",
    [
        "Who owes rent?",
        "Which tenants are overdue on rent?",
        "Show rent arrears",
        "How many payments were recorded?",
        "Who has paid this month?",
        "What is the collection rate?",
        "how much rent is outstanding",
        "List unpaid tenants",
    ],
)
def test_rent_money_questions_get_the_no_data_answer(query: str) -> None:
    assert rent_data_answer(query) == NO_RENT_DATA_ANSWER


@pytest.mark.parametrize(
    "query",
    [
        "Draft payment reminder",
        "What should I do first?",
        "List active leases",
        "When does the lease at Keizersgracht end?",
        "Show open tickets",
        "Is the boiler invoice approved?",
    ],
)
def test_other_questions_are_not_intercepted(query: str) -> None:
    assert rent_data_answer(query) is None


def test_nothing_is_intercepted_once_rent_data_is_mirrored(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(rent_guard, "RENT_DATA_AVAILABLE", True)
    assert rent_data_answer("Who owes rent?") is None
