"""proposer/v7 (M13, after the v6 real-model eval): what was settled is used, every missing item is its own question."""

from app.contracts import PromptRef
from app.llm.agents.proposer import DOSSIER_PROMPTS, PROPOSER_V7, ROLE_AWARE_PROMPTS
from app.llm.prompts import load_prompt


def _v(version: str) -> str:
    return load_prompt(PromptRef(name="proposer", version=version)).text


def test_v7_keeps_v6s_standard_and_safety_rule() -> None:
    v6, v7 = _v("v6"), _v("v7")
    for part in ("## Drafting standard", "## Safety rule", "## Who you are writing to", "## Commitments"):
        assert v6.split(part, 1)[1].split("\n## ", 1)[0] in v7, part


def test_v7_uses_what_was_settled_before_answering() -> None:
    v7 = _v("v7")
    assert "warrant" in v7.lower()
    assert "quoted" in v7.lower()


def test_v7_asks_each_missing_item_as_its_own_question() -> None:
    assert "its own question" in _v("v7")
    assert "?" in _v("v7").split("its own question", 1)[1][:200]


def test_v7_is_the_dossier_prompt() -> None:
    assert PROPOSER_V7.prompt.key == "proposer/v7"
    assert {"v6", "v7"} <= DOSSIER_PROMPTS
    assert "v7" in ROLE_AWARE_PROMPTS
