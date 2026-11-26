"""Tests for upgraded Vastgoed-calibrated prompts and real default persona."""

from app.context.persona import DEFAULT_NAME, DEFAULT_PATH
from app.contracts import Category, PromptRef
from app.contracts.categories import SHOWN_CATEGORIES
from app.llm.agents.doc_classifier import DOC_CLASSIFIER
from app.llm.agents.draft_research import DRAFT_RESEARCH
from app.llm.agents.person_memory import PERSON_MEMORY
from app.llm.agents.proposer import DOSSIER_PROMPTS, MAX_PERSONA_CHARS, PROPOSER_V8, ROLE_AWARE_PROMPTS
from app.llm.agents.understanding import UNDERSTANDING, sees_sender
from app.llm.prompts import load_prompt


def test_default_persona_is_real_harjot_persona_under_limit() -> None:
    text = DEFAULT_PATH.read_text("utf-8")
    assert DEFAULT_NAME == "Harjot Singh"
    assert "mock" not in text.lower()
    assert len(text) <= MAX_PERSONA_CHARS
    assert "Akkoord" in text
    assert "uitschrijving" in text


def test_understanding_v5_handles_invoices_reminders_and_all_categories() -> None:
    text = load_prompt(PromptRef(name="understanding", version="v5")).text
    assert UNDERSTANDING.prompt.key == "understanding/v5"
    assert sees_sender("v5")
    for c in (*SHOWN_CATEGORIES, Category.spam):
        assert f"`{c.value}`" in text
    assert "Jongeneel" in text
    assert "herinnering" in text
    assert "Bizziphone" in text


def test_proposer_v8_keeps_standard_and_adds_vastgoed_playbooks() -> None:
    v7 = load_prompt(PromptRef(name="proposer", version="v7")).text
    v8 = load_prompt(PromptRef(name="proposer", version="v8")).text
    assert PROPOSER_V8.prompt.key == "proposer/v8"
    assert "v8" in DOSSIER_PROMPTS
    assert "v8" in ROLE_AWARE_PROMPTS
    for part in ("## Drafting standard", "## Safety rule", "## Who you are writing to", "## Commitments"):
        assert v7.split(part, 1)[1].split("\n## ", 1)[0] in v8, part
    assert "1-line rule" in v8
    assert "uitschrijving" in v8
    assert "klein materiaal" in v8
    assert "Bizziphone" in v8


def test_supporting_agents_upgraded_to_new_prompt_versions() -> None:
    assert PERSON_MEMORY.prompt.key == "person_memory/v3"
    assert DOC_CLASSIFIER.prompt.key == "doc_classifier/v2"
    assert DRAFT_RESEARCH.prompt.key == "draft_research/v2"
    mem = load_prompt(PERSON_MEMORY.prompt).text
    doc = load_prompt(DOC_CLASSIFIER.prompt).text
    res = load_prompt(DRAFT_RESEARCH.prompt).text
    assert "ownership" in mem.lower()
    assert "taxatierapport" in doc
    assert "warmteservice.nl" in res
    assert "belastingdienst.nl" in res
