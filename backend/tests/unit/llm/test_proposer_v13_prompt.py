"""proposer/v13 (M13): v12 plus the fixes for its real-model misses on gemini-3.8-flash, all invented specifics."""

from app.contracts import PromptRef
from app.llm.agents.proposer import DOSSIER_PROMPTS, PROPOSER_V13, ROLE_AWARE_PROMPTS
from app.llm.prompts import load_prompt


def _v(version: str) -> str:
    return load_prompt(PromptRef(name="proposer", version=version)).text


def test_v13_keeps_v12s_standard_safety_and_answer_first_rules() -> None:
    v12, v13 = _v("v12"), _v("v13")
    parts = ("## Drafting standard", "## Safety rule", "## Answer first, ask last", "## Attachments", "## Persona",
             "## Who you are writing to", "## Output", "## Rules")  # fmt: skip
    for part in parts:
        assert v12.split(part, 1)[1].split("\n## ", 1)[0] in v13, part


def test_v13_never_names_a_price_harjot_would_accept() -> None:
    v13 = _v("v13")
    assert "the price Harjot would accept" in _v("v12")
    assert "the price Harjot would accept" not in v13
    assert "never name a counter-price" in v13


def test_v13_adds_nothing_to_a_quoted_rule_and_dates_nothing_the_data_does_not() -> None:
    v13 = _v("v13")
    assert "add no\n  day of the month" in v13
    assert "never by a date unless that date is written in the data" in v13


def test_v13_asks_each_requested_item_of_a_lump_sum_quote() -> None:
    assert "four requested\n  items are four questions" in _v("v13")


def test_v13_example_carries_no_figure_from_the_golden_set() -> None:
    assert "1.950" not in _v("v13")


def test_v13_stays_a_published_dossier_prompt() -> None:
    assert PROPOSER_V13.prompt.key == "proposer/v13"
    assert "v13" in DOSSIER_PROMPTS
    assert "v13" in ROLE_AWARE_PROMPTS
