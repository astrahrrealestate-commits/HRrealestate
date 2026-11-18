from collections.abc import Iterator

import pytest
from pydantic_ai import Agent

from app.core.settings import Settings
from app.llm.runtime import build_model, instrument_agents, model_name_for


def _s(**kw: object) -> Settings:
    return Settings(database_url="postgresql+psycopg://u:p@h/db", _env_file=None, **kw)  # type: ignore[arg-type]


@pytest.fixture(autouse=True)
def _reset_instrumentation() -> Iterator[None]:
    yield
    Agent.instrument_all(False)


def test_fake_model_by_default_and_model_string_otherwise() -> None:
    assert build_model(_s(), "understanding") != "fake"
    assert build_model(_s(llm_model="mistral:mistral-large-latest"), "understanding") == "mistral:mistral-large-latest"


def test_no_langfuse_keys_no_instrumentation() -> None:
    assert instrument_agents(_s()) is False


def test_langfuse_keys_instrument_every_agent_without_network() -> None:
    settings = _s(langfuse_host="https://cloud.langfuse.com", langfuse_public_key="pk", langfuse_secret_key="sk")
    assert instrument_agents(settings) is True


def test_gemini_model_gets_the_key_from_settings() -> None:
    from pydantic_ai.models.google import GoogleModel

    model = build_model(_s(llm_model="google-gla:gemini-2.5-flash", gemini_api_key="g-test"), "understanding")
    assert isinstance(model, GoogleModel)
    assert model.model_name == "gemini-2.5-flash"


def test_openai_model_gets_the_key_from_settings() -> None:
    from pydantic_ai.models.openai import OpenAIChatModel

    model = build_model(_s(llm_model="openai:gpt-4.1-mini", openai_api_key="sk-test"), "understanding")
    assert isinstance(model, OpenAIChatModel)


def test_concierge_uses_its_own_model() -> None:
    from pydantic_ai.models.google import GoogleModel

    settings = _s(llm_model="fake", concierge_model="google-gla:gemini-2.5-flash", gemini_api_key="g")
    assert isinstance(build_model(settings, "concierge"), GoogleModel)
    assert not isinstance(build_model(settings, "proposer"), GoogleModel)


def test_empty_concierge_model_falls_back_to_llm_model() -> None:
    from pydantic_ai.models.google import GoogleModel

    settings = _s(llm_model="google-gla:gemini-2.5-flash", concierge_model="", gemini_api_key="g")
    assert isinstance(build_model(settings, "concierge"), GoogleModel)
    assert build_model(_s(concierge_model=""), "concierge") != "fake"
    assert model_name_for(settings, "concierge") == "google-gla:gemini-2.5-flash"


def test_model_name_for_records_the_override() -> None:
    settings = _s(llm_model="openai:gpt-4.1-mini", concierge_model="google-gla:gemini-2.5-flash")
    assert model_name_for(settings, "concierge") == "google-gla:gemini-2.5-flash"
    assert model_name_for(settings, "proposer") == "openai:gpt-4.1-mini"


def test_concierge_model_is_still_wrapped_by_the_fallbacks() -> None:
    from pydantic_ai.models.fallback import FallbackModel

    settings = _s(
        llm_model="fake",
        concierge_model="google-gla:gemini-2.5-flash",
        llm_fallback_models=["openai:gpt-4.1-mini"],
        gemini_api_key="g",
        openai_api_key="sk-test",
    )
    assert isinstance(build_model(settings, "concierge"), FallbackModel)
