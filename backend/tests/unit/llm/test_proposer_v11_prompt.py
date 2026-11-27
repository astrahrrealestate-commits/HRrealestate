"""proposer/v11: answer and close from the dossier, ask only what is missing, negotiate only where money is saved."""

from app.contracts import PromptRef
from app.llm.agents.proposer import (
    DOSSIER_PROMPTS,
    PROPOSER_V11,
    ROLE_AWARE_PROMPTS,
    proposer_spec,
)
from app.llm.prompts import load_prompt
from tests.unit.llm.test_proposer_v6_prompt import _ctx


def _v(version: str) -> str:
    return load_prompt(PromptRef(name="proposer", version=version)).text


def test_v11_is_the_production_dossier_prompt() -> None:
    assert PROPOSER_V11.prompt.key == "proposer/v11"
    assert "v11" in DOSSIER_PROMPTS
    assert "v11" in ROLE_AWARE_PROMPTS
    assert proposer_spec(_ctx()) is PROPOSER_V11


def test_v11_keeps_v10s_safety_rules_and_output_shape() -> None:
    v10, v11 = _v("v10"), _v("v11")
    for part in ("## Persona", "## Output", "## Rules"):
        assert v10.split(part, 1)[1].split("\n## ", 1)[0] in v11, part
    assert "unread_attachments" in v11.split("## Safety rule", 1)[1].split("\n## ", 1)[0]


def test_v11_resolves_before_it_asks() -> None:
    v11 = _v("v11")
    assert "## Answer first, ask last" in v11
    assert "Default to answering" in v11
    assert "`resolved`" in v11.split("## Answer first, ask last", 1)[1].split("\n## ", 1)[0]


def test_v11_negotiates_only_where_money_can_be_saved() -> None:
    v11 = _v("v11")
    section = v11.split("## When to negotiate", 1)[1].split("\n## ", 1)[0]
    assert "money" in section
    assert "Never negotiate" in section


def test_v11_uses_attachments_and_never_asks_for_a_file_already_sent() -> None:
    v11 = _v("v11")
    assert "<attachment_text>" in v11
    assert "<unread_attachments>" in v11


def test_v11_checks_each_variant_before_it_returns() -> None:
    section = _v("v11").split("## Before you return", 1)[1].split("\n## ", 1)[0]
    assert "next concrete step" in section
    assert "liability" in section
    assert "outcome" in section
