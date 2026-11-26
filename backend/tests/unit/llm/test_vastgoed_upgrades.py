"""Tests for upgraded Vastgoed-calibrated prompts and real default persona."""

from app.context.persona import DEFAULT_NAME, DEFAULT_PATH
from app.contracts import Category, PromptRef, Understanding, WaitingSide
from app.contracts.categories import SHOWN_CATEGORIES
from app.llm.agents.doc_classifier import DOC_CLASSIFIER
from app.llm.agents.draft_research import DRAFT_RESEARCH
from app.llm.agents.person_memory import PERSON_MEMORY
from app.llm.agents.proposer import DOSSIER_PROMPTS, MAX_PERSONA_CHARS, PROPOSER_V9, ROLE_AWARE_PROMPTS
from app.llm.agents.understanding import UNDERSTANDING, sees_sender
from app.llm.prompts import load_prompt


def test_default_persona_is_real_harjot_persona_under_limit() -> None:
    text = DEFAULT_PATH.read_text("utf-8")
    assert DEFAULT_NAME == "Harjot Singh"
    assert "mock" not in text.lower()
    assert len(text) <= MAX_PERSONA_CHARS
    assert "Akkoord" in text
    assert "uitschrijving" in text
    assert "Was ontgaan" in text


def test_understanding_v6_handles_category_urgency_waiting_and_invoices() -> None:
    text = load_prompt(PromptRef(name="understanding", version="v6")).text
    assert UNDERSTANDING.prompt.key == "understanding/v6"
    assert sees_sender("v6")
    for c in (*SHOWN_CATEGORIES, Category.spam):
        assert f"`{c.value}`" in text
    assert "Jongeneel" in text
    assert "herinnering" in text
    assert "Bizziphone" in text
    assert "dagvaarding" in text
    assert "deurwaarder" in text
    assert "afsluiting" in text
    assert "waiting_side" in text
    assert "open_obligation" in text


def test_understanding_contract_defaults_pre_v6_rows_and_keeps_strict_schema() -> None:
    old_v5 = {
        "category": "finance",
        "intent": "Invoice check",
        "urgency": "low",
        "requires_reply": False,
        "entities": {"people": [], "unit_refs": [], "dates": [], "amounts": []},
        "suspicious": {"flag": False, "reason": None},
        "confidence": 0.9,
        "sender_role": "business",
        "needs_research": False,
        "research_questions": [],
        "prompt_version": "understanding/v5",
    }
    parsed = Understanding.model_validate(old_v5)
    assert parsed.waiting_side is WaitingSide.none
    assert parsed.open_obligation is None
    assert parsed.expected_days is None

    old_reply = {**old_v5, "requires_reply": True}
    assert Understanding.model_validate(old_reply).waiting_side is WaitingSide.owner
    schema = Understanding.model_json_schema()
    assert "waiting_side" in schema["required"]
    assert "open_obligation" in schema["required"]
    assert "expected_days" in schema["required"]


def test_proposer_v9_keeps_standard_and_adds_ownership_and_playbooks() -> None:
    v8 = load_prompt(PromptRef(name="proposer", version="v8")).text
    v9 = load_prompt(PromptRef(name="proposer", version="v9")).text
    assert PROPOSER_V9.prompt.key == "proposer/v9"
    assert "v9" in DOSSIER_PROMPTS
    assert "v9" in ROLE_AWARE_PROMPTS
    for part in ("## Drafting standard", "## Safety rule", "## Who you are writing to"):
        assert v8.split(part, 1)[1].split("\n## ", 1)[0] in v9, part
    assert "Sole Ownership Authority" in v9
    assert "1-line rule" in v9
    assert "uitschrijving" in v9
    assert "klein materiaal" in v9
    assert "Bizziphone" in v9
    assert "waiting_on_owner" in v9


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
