from collections.abc import Iterator

import pytest
from pydantic_ai import Agent

from app.core.settings import Settings
from app.llm.runtime import build_model, instrument_agents


def _s(**kw: object) -> Settings:
    return Settings(database_url="postgresql+psycopg://u:p@h/db", _env_file=None, **kw)  # type: ignore[arg-type]


@pytest.fixture(autouse=True)
def _reset_instrumentation() -> Iterator[None]:
    yield
    Agent.instrument_all(False)


def test_fake_model_by_default_and_model_string_otherwise() -> None:
    assert build_model(_s(), "understanding") != "fake"
    assert build_model(_s(llm_model="openai:gpt-4.1-mini"), "understanding") == "openai:gpt-4.1-mini"


def test_no_langfuse_keys_no_instrumentation() -> None:
    assert instrument_agents(_s()) is False


def test_langfuse_keys_instrument_every_agent_without_network() -> None:
    settings = _s(langfuse_host="https://cloud.langfuse.com", langfuse_public_key="pk", langfuse_secret_key="sk")
    assert instrument_agents(settings) is True
