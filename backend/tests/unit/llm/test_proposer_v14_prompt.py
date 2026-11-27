"""proposer/v14 (M13): v13 plus the fixes for its real-model misses on gemini-3.8-flash."""

from app.contracts import PromptRef
from app.llm.agents.proposer import DOSSIER_PROMPTS, PROPOSER_V14, ROLE_AWARE_PROMPTS
from app.llm.prompts import load_prompt


def _v(version: str) -> str:
    return load_prompt(PromptRef(name="proposer", version=version)).text


def _section(text: str, heading: str) -> str:
    return text.split(heading, 1)[1].split("\n## ", 1)[0]


def test_v14_keeps_v13s_standard_safety_persona_and_rules() -> None:
    v13, v14 = _v("v13"), _v("v14")
    parts = ("## Sole Ownership Authority", "## Drafting standard", "## Safety rule", "## Attachments",
             "## When to negotiate", "## Commitments & Open-Obligation Pairing", "## Persona",
             "## Who you are writing to", "## Output", "## Rules")  # fmt: skip
    for part in parts:
        assert _section(v14, part) == _section(v13, part), part


def test_v14_carries_no_example_that_promises_a_warranty() -> None:
    assert "onder de garantie" in _v("v13")
    assert "onder de garantie" not in _v("v14")
    assert "the contractor's warranty if it recurs" not in _v("v14")
    assert "Never promise a warranty, a return visit" in _v("v14")


def test_v14_asks_each_quote_item_once_and_names_the_rent_roll() -> None:
    v14 = _v("v14")
    assert "never also a sentence or\n  question that lists them together" in v14
    assert "huurlijst (rent roll)" in v14


def test_v14_ends_every_variant_with_the_next_step() -> None:
    assert "Every variant, a short answer and a closing reply too, ends with the next concrete step" in _v("v14")


def test_v14_is_a_dossier_prompt() -> None:
    assert PROPOSER_V14.prompt.key == "proposer/v14"
    assert "v14" in DOSSIER_PROMPTS
    assert "v14" in ROLE_AWARE_PROMPTS
