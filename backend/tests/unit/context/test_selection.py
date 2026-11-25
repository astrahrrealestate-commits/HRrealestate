"""Unit tests for relevance ranking and tiered rendering of open cases."""

from uuid import UUID, uuid4

from app.context.selection import DETAIL_CASES, rank_cases, render_case_lines
from app.llm.agents.owner_qa import CaseBrief


def _case(label: str, urgency: str = "normal", summary: str = "", case_id: UUID | None = None) -> CaseBrief:
    return CaseBrief(case_id or uuid4(), label, "open", urgency, summary)


def test_urgency_orders_cases_when_the_question_names_nothing() -> None:
    low, emergency, high = _case("a", "low"), _case("b", "emergency"), _case("c", "high")
    ranked = rank_cases([low, emergency, high], "what is going on?")
    assert ranked == [emergency, high, low]


def test_a_case_named_in_the_question_beats_urgency() -> None:
    boiler = _case("Boiler broken · Keizersgracht 42-A", "low", "no hot water")
    leak = _case("Leak · Prinsengracht 9", "emergency", "water on the floor")
    ranked = rank_cases([leak, boiler], "status of the boiler at Keizersgracht?")
    assert ranked[0] is boiler


def test_the_ticket_ref_in_the_question_matches() -> None:
    target = _case("Door", "low", case_id=UUID("01a1a4d1-0000-7000-8000-00abcdef1234"))
    other = _case("Roof", "emergency")
    assert rank_cases([other, target], "update on ticket #ef1234 please")[0] is target


def test_the_timestamp_head_of_an_id_is_not_a_ticket_ref() -> None:
    target = _case("Door", "low", case_id=UUID("01a1a4d1-0000-7000-8000-00abcdef1234"))
    other = _case("Roof", "emergency")
    assert rank_cases([other, target], "update on ticket #01a1a4 please")[0] is other


def test_the_focus_case_comes_first() -> None:
    focus = _case("Door", "low")
    other = _case("Roof", "emergency")
    assert rank_cases([other, focus], "what next?", focus_case_id=str(focus.case_id))[0] is focus


def test_ranking_is_stable_for_equal_cases() -> None:
    a, b, c = _case("same"), _case("same"), _case("same")
    assert rank_cases([a, b, c], "x") == [a, b, c]


def test_only_the_top_cases_carry_a_summary_and_every_case_stays_listed() -> None:
    cases = [_case(f"Case {i}", summary=f"unique-summary-{i}") for i in range(DETAIL_CASES + 4)]
    lines = render_case_lines(cases)
    text = "\n".join(lines)
    assert all(str(c.case_id) in text for c in cases)
    assert f"unique-summary-{DETAIL_CASES - 1}" in text
    assert f"unique-summary-{DETAIL_CASES}" not in text
    assert "4 more cases" in text


def test_summaries_are_clipped_and_whitespace_collapsed() -> None:
    lines = render_case_lines([_case("Leak", summary="word   " * 600)])
    assert len(lines[0]) < 1400
    assert "   " not in lines[0]


def test_no_cases_renders_nothing() -> None:
    assert render_case_lines([]) == []


def test_a_house_number_in_the_question_picks_the_right_case_on_a_shared_street() -> None:
    cases = [_case(f"Tenant {i} · Lijnbaansgracht {10 + i}-B", "normal") for i in range(10)]
    wanted = cases[7]
    ranked = rank_cases(cases, "status of the problem at Lijnbaansgracht 17-B?")
    assert ranked[0] is wanted


def test_a_unit_code_with_digits_counts_as_a_match_even_when_short() -> None:
    a, b = _case("Door · unit 4C"), _case("Door · unit 9F")
    assert rank_cases([a, b], "what about 9F?")[0] is b


def test_listing_stops_at_the_character_budget_and_says_how_many_were_left_out() -> None:
    cases = [_case(f"Case number {i} with a fairly long label", summary="s") for i in range(80)]
    lines = render_case_lines(cases, max_chars=3000)
    text = "\n".join(lines)
    assert len(text) <= 3000
    assert "not listed" in lines[-1]
    assert str(cases[0].case_id) in text
    assert str(cases[79].case_id) not in text


def test_every_case_is_listed_when_the_budget_is_big_enough() -> None:
    cases = [_case(f"Case {i}") for i in range(30)]
    text = "\n".join(render_case_lines(cases, max_chars=20000))
    assert all(str(c.case_id) in text for c in cases)
    assert "not listed" not in text
