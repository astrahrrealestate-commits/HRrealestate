"""Unit tests for model_calls measurement fields (tokens_cached, prefix_hash)."""

from unittest.mock import MagicMock, patch
from uuid import uuid4

from app.contracts import Channel
from app.core.settings import Settings
from app.llm.agents.understanding import UNDERSTANDING, understanding_prompt
from app.llm.calls import CallContext, run_agent


def test_run_agent_records_prefix_hash_and_tokens_cached() -> None:
    settings = Settings(database_url="postgresql+psycopg://u:p@localhost:1/db", _env_file=None)  # type: ignore[call-arg]
    ctx = CallContext(company_id=uuid4(), purpose="triage", prefix_hash="prefix_hash_12345")
    prompt = understanding_prompt(
        text="Lekkage in badkamer",
        channel=Channel.whatsapp,
    )
    mock_engine = MagicMock()

    with patch("app.llm.calls._record") as mock_record:
        res = run_agent(mock_engine, settings, UNDERSTANDING, prompt, ctx)
        assert res.model_call_id is not None
        mock_record.assert_called_once()
        call_row = mock_record.call_args.args[1]
        assert call_row.prefix_hash == "prefix_hash_12345"
        assert call_row.tokens_in is not None
        assert call_row.tokens_cached in (0, None)
