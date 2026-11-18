from app.db.enums import SendStatus, TurnStatus
from app.dev.demo_dashboard import TENANT_E164, Facts, dashboard_problems, targets

GOOD = Facts(1, ((TENANT_E164, SendStatus.sent),), (TurnStatus.done,), 1)


def test_good_facts_have_no_problems() -> None:
    assert dashboard_problems(GOOD, targets()) == []


def test_each_failure_is_reported() -> None:
    bad = Facts(0, (), (TurnStatus.failed,), 2)
    found = dashboard_problems(bad, targets())
    assert len(found) == 4


def test_send_to_a_stranger_or_unsent_is_a_problem() -> None:
    assert dashboard_problems(Facts(1, (("+31600000000", SendStatus.sent),), (TurnStatus.done,), 1), targets())
    assert dashboard_problems(Facts(1, ((TENANT_E164, SendStatus.failed),), (TurnStatus.done,), 1), targets())


def test_no_planner_call_is_a_problem() -> None:
    assert dashboard_problems(Facts(1, ((TENANT_E164, SendStatus.sent),), (TurnStatus.done,), 0), targets()) == [
        "0 model calls for the agent turn, expected 1 (the planner)"
    ]


def test_two_sends_for_one_action_is_a_problem() -> None:
    two = Facts(1, ((TENANT_E164, SendStatus.sent),) * 2, (TurnStatus.done,), 1)
    assert dashboard_problems(two, targets()) == ["sends: 2/1 for the decided action"]
