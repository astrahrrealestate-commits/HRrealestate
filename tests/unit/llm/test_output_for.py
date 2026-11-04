from pydantic_ai import PromptedOutput

from app.contracts import Proposal
from app.core.settings import Settings
from app.llm.agents.dd_reader import DD_READER
from app.llm.agents.proposer import PROPOSER, PROPOSER_PERSONA
from app.llm.agents.quote_reader import QUOTE_READER
from app.llm.runtime import output_for


def _settings(model: str) -> Settings:
    return Settings(database_url="postgresql+psycopg://u:p@h/db", llm_model=model, _env_file=None)  # type: ignore[arg-type]


def test_gemini_gets_the_schema_in_the_prompt_for_flagged_agents() -> None:
    out = output_for(_settings("google-gla:gemini-2.5-flash"), Proposal, gemini_prompted=True)
    assert isinstance(out, PromptedOutput)


def test_other_providers_and_unflagged_agents_keep_the_strict_tool_schema() -> None:
    assert output_for(_settings("openai:gpt-4.1-mini"), Proposal, gemini_prompted=True) is Proposal
    assert output_for(_settings("fake"), Proposal, gemini_prompted=True) is Proposal
    assert output_for(_settings("google-gla:gemini-2.5-flash"), Proposal) is Proposal


def test_agents_whose_schema_gemini_rejects_are_flagged() -> None:
    assert all(spec.gemini_prompted for spec in (PROPOSER, PROPOSER_PERSONA, DD_READER, QUOTE_READER))
