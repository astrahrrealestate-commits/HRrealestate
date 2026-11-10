"""A conversation's focus is only what the owner and the agent actually discussed, never the portfolio's top case."""

from app.api.agent.focus import NEW_CHAT_FACT, new_chat_fact, next_focus


def test_a_turn_without_a_card_leaves_an_empty_focus_empty() -> None:
    assert next_focus({}, None) == {}


def test_a_turn_without_a_card_keeps_the_existing_focus() -> None:
    assert next_focus({"case_id": "c-1", "unit_label": "Singel 412"}, None) == {
        "case_id": "c-1",
        "unit_label": "Singel 412",
    }


def test_a_card_sets_only_the_fields_it_carries() -> None:
    card = {
        "caseId": "c-2",
        "unitLabel": "Keizersgracht 42-A",
        "recipient": None,
        "contractor": "Kevin",
        "actionId": "a-1",
    }
    assert next_focus({"recipient": "Old"}, card) == {
        "recipient": "Old",
        "case_id": "c-2",
        "unit_label": "Keizersgracht 42-A",
        "contractor": "Kevin",
        "last_action_id": "a-1",
    }


def test_the_new_chat_fact_appears_only_before_the_first_turn() -> None:
    assert new_chat_fact(prior_turns=0) == NEW_CHAT_FACT
    assert new_chat_fact(prior_turns=2) == ""
