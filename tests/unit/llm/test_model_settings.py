from app.core.settings import Settings
from app.llm.agents.case_summary import CASE_SUMMARY
from app.llm.agents.concierge import CONCIERGE
from app.llm.agents.proposer import PROPOSER, PROPOSER_DOCS, PROPOSER_GUIDED, PROPOSER_PERSONA
from app.llm.agents.understanding import UNDERSTANDING
from app.llm.calls import model_settings


def _settings() -> Settings:
    return Settings(database_url="postgresql+psycopg://u:p@h/db", _env_file=None)  # type: ignore[call-arg]


def test_inbox_critical_path_agents_do_not_spend_hidden_thinking_tokens() -> None:
    assert model_settings(_settings(), CASE_SUMMARY)["thinking"] is False
    assert model_settings(_settings(), UNDERSTANDING)["thinking"] == "minimal"
    for proposer in (PROPOSER, PROPOSER_DOCS, PROPOSER_GUIDED, PROPOSER_PERSONA):
        assert model_settings(_settings(), proposer)["thinking"] == "minimal"


def test_agents_without_a_choice_keep_the_provider_default_and_the_caps() -> None:
    chosen = model_settings(_settings(), CONCIERGE)
    assert "thinking" not in chosen
    assert chosen["max_tokens"] == _settings().llm_max_output_tokens
    assert chosen["timeout"] == _settings().llm_timeout_sec
