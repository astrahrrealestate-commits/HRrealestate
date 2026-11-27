"""Unit tests for the fast retrieval-gap enhance planner agent."""

from pydantic_ai import Agent

from app.contracts.enhance import EnhancePlan
from app.llm.agents.enhance_planner import ENHANCE_PLANNER, enhance_planner_prompt
from app.llm.fakes import model_for
from app.llm.prompts import load_prompt


def test_enhance_planner_prompt_loads_and_renders() -> None:
    loaded = load_prompt(ENHANCE_PLANNER.prompt)
    assert ENHANCE_PLANNER.prompt.key == "enhance_planner/v1"
    assert loaded.text
    prompt = enhance_planner_prompt(
        "Mention the deposit clause and WWS law",
        "Beste huurder, dank voor uw bericht.",
        case_summary="Tenant asking about deposit return",
        category="legal",
        loaded_sources=["ROZ 2017"],
    )
    assert "<instruction>" in prompt
    assert "<current_draft>" in prompt
    assert "<dossier_summary>" in prompt
    assert "ROZ 2017" in prompt


def test_fake_enhance_planner_skips_lookups_for_style_edits() -> None:
    agent = Agent(
        model_for("enhance_planner"),
        output_type=EnhancePlan,
        system_prompt=load_prompt(ENHANCE_PLANNER.prompt).text,
    )
    style_res = agent.run_sync(
        enhance_planner_prompt(
            "Make it shorter and friendlier", "Beste Jan,", case_summary="Leak", category="maintenance"
        )
    )
    assert style_res.output == EnhancePlan()

    fact_res = agent.run_sync(
        enhance_planner_prompt(
            "Check lease deposit clause, past email promises, and Dutch legal WWS rule",
            "Beste Jan,",
            case_summary="Deposit",
            category="legal",
        )
    )
    assert fact_res.output.rag_queries
    assert fact_res.output.mail_queries
    assert fact_res.output.web_questions
