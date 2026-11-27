"""proposer/v12 (M13): v11 plus the fixes from its real-model misses on gemini-3.8-flash."""

from app.contracts import PromptRef
from app.llm.agents.proposer import DOSSIER_PROMPTS, PROPOSER_V12, ROLE_AWARE_PROMPTS
from app.llm.prompts import load_prompt


def _v(version: str) -> str:
    return load_prompt(PromptRef(name="proposer", version=version)).text


def test_v12_keeps_v11s_standard_safety_and_answer_first_rules() -> None:
    v11, v12 = _v("v11"), _v("v12")
    for part in ("## Drafting standard", "## Safety rule", "## Answer first, ask last", "## Attachments"):
        assert v11.split(part, 1)[1].split("\n## ", 1)[0] in v12, part


def test_v12_cites_no_statute_that_is_not_in_the_data() -> None:
    assert "BW" in _v("v12")
    assert "never assume" in _v("v12").lower()


def test_v12_never_writes_the_word_liability_even_to_deny_it() -> None:
    assert "aansprakelijk" in _v("v12")
    assert "not even to deny" in _v("v12")


def test_v12_negotiates_terms_with_the_quotes_own_numbers_without_a_reference() -> None:
    text = _v("v12")
    assert "quote's own figures" in text
    assert "30%" in text


def test_v12_stays_a_published_dossier_prompt() -> None:
    assert PROPOSER_V12.prompt.key == "proposer/v12"
    assert "v12" in DOSSIER_PROMPTS
    assert "v12" in ROLE_AWARE_PROMPTS
