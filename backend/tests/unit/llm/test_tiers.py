"""Two model tiers, Gemini only (M13 T5): quality agents think hard on the strongest model, the rest stay fast."""

from typing import Any

import pytest

from app.core.settings import Settings
from app.core.startup import production_problems
from app.llm.agents.case_summary import CASE_SUMMARY
from app.llm.agents.proposer import PROPOSER, PROPOSER_PERSONA
from app.llm.agents.understanding import UNDERSTANDING
from app.llm.calls import model_settings
from app.llm.runtime import model_name_for
from app.llm.tiers import QUALITY_AGENTS, tier_of
from tests.unit.core.test_startup import REAL

PRO = "google-gla:gemini-3.5-pro"
FLASH = "google-gla:gemini-3.8-flash"


def _s(**kw: Any) -> Settings:
    return Settings(database_url="postgresql+psycopg://u:p@h/db", _env_file=None, **kw)  # type: ignore[call-arg]


def test_the_quality_tier_names_the_four_agents() -> None:
    assert frozenset({"proposer", "draft_research", "super_agent_research", "person_memory"}) == QUALITY_AGENTS
    assert tier_of("proposer") == "quality"
    assert tier_of("understanding") == "fast"


def test_quality_agents_use_the_quality_model_with_high_thinking() -> None:
    s = _s(llm_model=FLASH, llm_quality_model=PRO)
    for agent in QUALITY_AGENTS:
        assert model_name_for(s, agent) == PRO
    for spec in (PROPOSER, PROPOSER_PERSONA):
        assert model_settings(s, spec)["thinking"] == "high"


def test_fast_agents_keep_llm_model_and_their_thinking() -> None:
    s = _s(llm_model=FLASH, llm_quality_model=PRO)
    for agent in ("understanding", "link_check", "case_summary", "doc_reader", "quote_reader"):
        assert model_name_for(s, agent) == FLASH
    assert model_settings(s, UNDERSTANDING)["thinking"] == "minimal"
    assert model_settings(s, CASE_SUMMARY)["thinking"] is False
    assert model_settings(s, UNDERSTANDING)["timeout"] == s.llm_timeout_sec


def test_the_concierge_override_still_wins_for_the_concierge() -> None:
    s = _s(llm_model=FLASH, llm_quality_model=PRO, concierge_model="google-gla:gemini-3.8-flash-lite")
    assert model_name_for(s, "concierge") == "google-gla:gemini-3.8-flash-lite"


def test_unset_quality_model_falls_back_to_llm_model() -> None:
    assert model_name_for(_s(llm_model=FLASH), "proposer") == FLASH


def test_an_empty_model_variable_means_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    """`NAME=` in an env file parses to None (env_parse_none_str); a model name field reads that as empty."""
    monkeypatch.setenv("CONCIERGE_MODEL", "")
    monkeypatch.setenv("LLM_QUALITY_MODEL", "")
    s = _s(llm_model=FLASH)
    assert (s.concierge_model, s.llm_quality_model) == ("", "")
    assert model_name_for(s, "proposer") == FLASH


def test_quality_calls_get_the_longer_timeout_and_token_cap() -> None:
    s = _s(llm_model=FLASH, llm_quality_model=PRO)
    chosen = model_settings(s, PROPOSER)
    assert (chosen["timeout"], chosen["max_tokens"]) == (180, 16000)
    assert (s.llm_quality_timeout_sec, s.llm_quality_max_output_tokens) == (180, 16000)
    fast = model_settings(s, UNDERSTANDING)
    assert (fast["timeout"], fast["max_tokens"]) == (s.llm_timeout_sec, s.llm_max_output_tokens)


GEMINI_PROD: dict[str, Any] = {**REAL, "llm_model": FLASH, "llm_quality_model": PRO, "gemini_api_key": "g"}


@pytest.mark.parametrize(
    ("override", "fragment"),
    [
        ({"llm_model": "openai:gpt-4.1-mini"}, "llm_model"),
        ({"llm_quality_model": "openai:gpt-5"}, "llm_quality_model"),
        ({"concierge_model": "groq:llama-3.3-70b"}, "concierge_model"),
        ({"llm_fallback_models": ["openai:gpt-4.1-mini"]}, "llm_fallback_models"),
        ({"embedding_model": "openai:text-embedding-3-small"}, "embedding_model"),
    ],
)
def test_prod_refuses_a_non_gemini_model_or_fallback(override: dict[str, Any], fragment: str) -> None:
    problems = production_problems(_s(env="prod", **{**GEMINI_PROD, **override}))
    assert any(fragment in p and "Gemini" in p for p in problems), problems


@pytest.mark.parametrize("field", ["llm_model", "llm_quality_model", "concierge_model", "embedding_model"])
def test_prod_refuses_fake(field: str) -> None:
    problems = production_problems(_s(env="prod", **{**GEMINI_PROD, field: "fake"}))
    assert any(field in p for p in problems), problems


def test_prod_accepts_gemini_everywhere_with_unset_overrides() -> None:
    settings = _s(env="prod", **{**GEMINI_PROD, "llm_fallback_models": [FLASH]})
    assert not [p for p in production_problems(settings) if "model" in p]
