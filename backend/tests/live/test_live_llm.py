"""LLM go-live check: the configured real model returns valid contract output for the understanding prompt v1.

Runs the published prompt on one synthetic Dutch message (no tenant data). Costs one small model call.
"""

import pytest
from pydantic_ai import Agent

from app.contracts import Category, Channel, Understanding, Urgency
from app.core.settings import Settings
from app.llm.agents.understanding import UNDERSTANDING, understanding_prompt
from app.llm.prompts import load_prompt
from app.llm.runtime import build_model


@pytest.mark.live("LLM_MODEL")
def test_real_model_triages_a_dutch_emergency(live_settings: Settings) -> None:
    from app.core.startup import production_problems

    key_problems = [p for p in production_problems(live_settings.model_copy(update={"env": "prod"})) if "api_key" in p]
    assert not key_problems, key_problems  # the provider's key is configured (OPENAI_API_KEY or GEMINI_API_KEY)
    agent = Agent(
        build_model(live_settings, "understanding"),
        output_type=Understanding,
        instructions=load_prompt(UNDERSTANDING.prompt).text,
        retries=2,
    )
    prompt = understanding_prompt("Help! Er stroomt water door het plafond van de badkamer.", Channel.whatsapp)
    out = agent.run_sync(prompt).output
    assert out.category is Category.maintenance
    assert out.urgency in (Urgency.emergency, Urgency.high)
    assert out.suspicious.flag is False
